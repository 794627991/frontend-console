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
        // v3.3.2(P7)：init#2=CLI 自发新回合（机器唤醒：后台代理完成/协作回传）
        // ——亮运行态的同时重开上一回合（30min 护栏），续跑工作回原组不切头
        if (_HG.initN > 1 && (!_HG.busy || _HG.hold)) { setBusy(true); _hgTurnReopen(false); }
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
        // v3.4.43（用户实锤「目录混进 Task · 推送到 origin master」）：CLI 对
        // run_in_background 的 Bash 等主链工具也发 task_started/task_notification
        // （is_backgrounded=true、subagent_type 空）——协作包装判定命中后给它
        // 建了 collab 档案（type 缺省 'Task'、desc=Bash description），目录里
        // 伪装成子代理、点开必「未找到转写」。判别：无 peerSent 且 tool_use
        // 行不是 Task/Agent（Bash 行在 rowById，_name 可查）=纯后台 shell，
        // 整个 Task 生命周期处理跳过（不建档不建段不进目录）
        const _shRow = (_HG.rowById || {})[tid];
        const _shBg = sub === 'task_started' && !((_HG.peerSent || {})[tid])
          && _shRow && _shRow._name !== 'Task' && _shRow._name !== 'Agent';
        if (_shBg) {
          // v3.5.22（用户需求「task 与子代理区分，create/done/取消可见」）：
          // 后台 shell 不再静默忽略——建档 _HG.tasks + 消息流任务卡；完成
          // 定格在下方 task_notification 分支（_shBgT 判定同款）。子代理
          // 体系零污染（不进 _HG.agents/不建段/不进目录子代理分组）
          _taskStart(tid, o.description || _shRow._preview || '');
        } else if (sub === 'task_notification' && tid && (_HG.tasks || {})[tid]
                   && !((_HG.peerSent || {})[tid])) {
          // 后台任务完成定格（与子代理 notification 分流：tasks 档案优先）
          _taskFinish(tid, o.is_error ? 'err' : 'done', o.summary || '');
        } else if (sub === 'task_started'
            && _isCollabWrap(o.subagent_type, o.is_backgrounded)) {
          _subDrop(tid);
          if (tid) {
            const _to = (_HG.peerSent || {})[tid];
            const _real = (_to && /^[0-9a-zA-Z_-]{8,64}$/.test(String(_to)))
              ? String(_to) : '';
            (_HG.agents || (_HG.agents = {}))[tid] = {
              type: o.subagent_type || 'Task', desc: o.description || '',
              t0: Date.now(), done: false, doneAt: 0,
              collab: true, bg: true,
              // v3.5.158：peerSent miss 时 taskId 降级为包装 task_id（无转写
              // 的「幻影档案」）——unresolved 标记让 _subReopen/_subDirRowClick
              // 走 subagent_resolve 解析漏斗而非拿降级 id 硬开回放
              unresolved: !_real,
              taskId: _real || (o.task_id || '') };
            // 段头名字优先用转交收件人（与「已转交」线同名对齐），否则角色
            // 类型名。段不挂 hgSub（无实况流，窗格钮不画）；真实 id 在手则
            // 建段即落 hgSubr——运行中即可「▣ 回放」围观转写，也是切会话
            // 往返后 DOM 兜底轮询的 id 来源（随快照携带）
            _subBlkGet(tid, { live: true, collab: true, bg: true, fold: true,
              label: (typeof _peerDesc === 'function'
                  ? _peerDesc(_to, (_HG.peerMsg || {})[tid]) : '')
                || (_AGENT_LABEL[o.subagent_type] || o.subagent_type || '代理'),
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
        } else if (tid && !_shBg) {
          if (!_HG.agents && sub === 'task_started') _HG.agents = {};
          let a = _HG.agents && _HG.agents[tid];
          if (!a && _HG.agents && sub === 'task_started') {
            // 兜底建档（Task tool_use 已建档时零改动）：t0 用当下近似
            // v3.5.296（用户实锤「SendMessage 往来的代理显示成 Task」）：
            // 续派事件 description 恒空——peerSent[tid] 命中即补 to 原名
            //（_peerLabel：角色名出中文/已知 id 反查档案名），tab 名、状态
            // 胶囊「✦N …」、窗格全链走档案 desc，此处修好全好
            a = _HG.agents[tid] = {
              type: o.subagent_type || 'Task',
              desc: o.description || (typeof _peerDesc === 'function'
                ? _peerDesc((_HG.peerSent || {})[tid], (_HG.peerMsg || {})[tid]) : ''),
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
              // v3.2.30：agentId 到手即冲 live 来向队列（窗格已开的目标立即收到）
              if (a.taskId) _subUserFlush(a.taskId);
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
            // v3.4.52：跨会话完成信号入桶——档案被切会话清场时，运行中档案
            // 在 liveAgentsBy 桶里，直达桶内置 done（防切回后假运行）
            for (const _ls in (_HG.liveAgentsBy || {})) {
              const _la = _HG.liveAgentsBy[_ls][tid];
              if (_la && !_la.done) {
                _la.done = true; _la.doneAt = Date.now();
                _la.err = !!(o.status && o.status !== 'completed' && o.status !== 'success');
                _la.result = String(o.summary || '').trim().slice(0, 400) || _la.result;
                break;
              }
            }
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
      // v3.3.2(P7)：空闲期 assistant 到达多为机器唤醒续跑——同步重开上一回合
      if (!isSub && !_HG.busy && _HG.sid) { setBusy(true); _hgTurnReopen(false); }
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
                // v3.4.52：档案记归属会话——切会话暂存/回填的判据
                sid: _HG.sid,
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
            // v3.4.88（识图卡化）：转交线退役——建折叠卡（emoji+名+prompt 摘要
            // +「识图中」徽章+秒表）入回合时间线，与 Bash/思考同语言；prompt
            // 全文随卡 dataset（点开可见）
            const el = _hgVisionCardBuild(Object.assign({}, b.input || {}, {
              __tid: b.id || '',
              __chan: (b.name === 'mcp__vision__analyze_image' ? '兜底' : '主')
            }));
            _tlPlace(el, b.name, b.input || null);   // 非 explore → 直挂组时间线
            (_HG.visionCalls || (_HG.visionCalls = {}))[b.id] = el;
            // v3.5.237（用户需求「调用识图工具，头部把识图也显示上」）：识图
            // 计数进组 counts.visionN（与工具分列），实时刷头副位
            {
              const _g = _HG.grp;
              if (_g) {
                _g.counts = _g.counts || {};
                _g.counts.visionN = (_g.counts.visionN || 0) + 1;
                try { _turnHeadSubPaint(_g); } catch (_) {}
              }
            }
            _hgPeerTimerStart(el, +el.dataset.t0 || Date.now());   // 卡内 .hg-peer-t 钩子走表
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
              // v3.5.308（用户令「显示当时的任务名」）：任务内容首行随键存——
              // 建档 desc 的最终兜底（角色短名 · 任务首行，如「审核 · 复审请求」）
              (_HG.peerMsg || (_HG.peerMsg = {}))[b.id] =
                String(b.input.message || '').replace(/\s+/g, ' ').trim().slice(0, 60);
              // v3.2.30（用户实锤「运行中的代理看不到发给它的消息」）：追加
              // message 入 live 来向队列（按目标 agentId 键——运行中窗格即刻
              // 收到，未开的等绑 id 后冲）
              _subUserQueue(String(b.input.to), b.input.message || '');
              // v3.4.68（用户定调「这个也不应该存在吧？等待啥呢？」）：to 命中
              // 本会话子代理档案（agentId/taskId 匹配）=续派复核，不是跨会话
              // 协作——不画转交线（.h-switch 线是「等待回传」语义的载体，线
              // 不存在则动态页协作行/全局等待态无从谈起）。档案/段锚照建
              // （生命周期与内容归属是真的）。首次续派时原子代理档案的
              // agentId 已由完成回填（10-sse task_result 路径），可命中。
              const _aid0 = String(b.input.to);
              const _localResend = Object.values(_HG.agents || {})
                .some(a => a && (a.agentId === _aid0 || a.taskId === _aid0));
              // v2.49：协作归一子代理段——SendMessage 转交线隐藏（数据锚全保留：
              // dataset.t0/peer/done/psum 照写，面板协作行/定格配对/快照序列化
              // 链路不动），识图转交原形态保留（唯一例外）
              if (!_localResend) {
                const _rEl = renderPeerRelay(b.input.to);
                if (_rEl && !_aid0.includes('识图'))
                  _rEl.style.display = 'none';
              }
              // v2.58：续派（to=agentId 形态）立即建**新段**——轮询/回传/回填
              // 全部归属新段。旧实现等首个子代理事件才兜底建段（常缺失），续审
              // 内容经轮询流回旧段（用户实锤「咋又跑上一个审计会话里去了」）。
              // 识图不建（转交通道不同）
              if (/^[0-9a-zA-Z_-]{8,64}$/.test(_aid0)) {
                const _aid = _aid0;
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
      // v3.4.66：CLI 注入的 meta 图片标注行（Read 回图 "[Image: original …]"
      // 纯标注串）不是真人输入——放行会被 closeRun() 腰斩工具 run 分组（重建
      // 路还会渲染成幽灵用户泡+切错窗口起点，transcript.py 已同步整行丢弃）。
      // 只精确打击纯标注串：isMeta 里还混着 peer 回传行（Another Claude
      // session），不可全量拦
      if (o.isMeta && typeof c0 === 'string' && /^\[Image: [^\]]+\]$/.test(c0.trim())) return;
      // v3.4.82（用户实锤「这个明显不是我的消息」）：isMeta 的纯文本注入行
      //（Skill 文档等机器给模型的上下文）不是真人输入——渲染成用户气泡=
      // 「别人往我的会话里塞了消息」的观感。弱化成系统提示行（文档全文在
      // 模型上下文里，UI 只留一行痕迹）；peer 回传（Another 前缀）不受影响
      if (o.isMeta) {
        const _mt = typeof c0 === 'string' ? c0
          : (Array.isArray(c0) && c0.every(b => !b || b.type === 'text')
             ? c0.filter(b => b && b.type === 'text').map(b => b.text).join('\n') : '');
        // v3.4.82R（复核 P2/P3·语料实证）：豁免两类——①贴图回显行
        //（[Image: source: …] list 全文本块形态 108 条，v3.2.16 定调消息列
        // 永不出现图片链接行→静默丢）；②机器续跑标记（v3.2.12 定调不进
        // 聊天框→静默丢）。其余 isMeta 纯文本（skill 文档）→ sysnote 弱化
        const _mtLines = _mt ? _mt.split('\n').map(x => x.trim()).filter(Boolean) : [];
        const _allImgEcho = _mtLines.length > 0
          && _mtLines.every(x => /^\[Image: [^\]]+\]$/.test(x));
        const _noise = /^\[Request interrupted|^\[Request cancelled by user|^Continue from where you left off/.test(_mt.trim());
        if (_allImgEcho || _noise) return;
        if (_mt && !_mt.trim().startsWith('Another Claude session')) {
          renderSysNote('skill-doc', '已注入机器上下文：' + _mt.replace(/\s+/g, ' ').trim().slice(0, 60) + '（供模型参考，非用户消息）');
          return;
        }
      }
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
          // v3.4.81（用户实锤「僵尸子代理 工作 6m35s」）：SendMessage 发送失败
          // 的回执是 content={"success":false,"message":...}（is_error=false，
          // 无 task_notification 跟进）——bg 包装档案旧只等 notification =
          // 永挂运行中。失败 JSON 即刻收尾（err=true，摘要入档）
          const _rt0 = resultText(b);
          const _sendFail = /^\s*\{\s*"success"\s*:\s*false/.test(_rt0);
          if (a && !a.done && (_sendFail || !a.bg)) {
            a.done = true;
            a.doneAt = Date.now();
            a.err = !!b.is_error || _sendFail;
            a.result = _rt0.slice(0, 400);
            // v2.38：agentId 落档——Task tool_result 文本自带「agentId: xxx」
            //（与 task_started 的 task_id 同源），回放窗格靠它定位子代理转写
            a.agentId = a.taskId
              || (_rt0.match(/(?<![a-zA-Z])agentId[:"':\s]+([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
            _subClose(b.tool_use_id, a.err);   // v2.33：窗格 tab 定格 ✓/✗
            // v3.4.82（用户实锤「等待协作回传 20m56s」假等待）：SendMessage
            // 失败的转交线也要定格——派发时按 peerSent 建过隐藏线（外部 id
            // 形态），失败后线不定格=「等待回传」秒表永走。按 tool_use_id 反查
            // peerSent 定格对应线（摘要入 psum）
            if (_sendFail) {
              const _fpeer = (_HG.peerSent || {})[b.tool_use_id];
              if (_fpeer) {
                const _fl = _hgPeerLines().find(el => el.dataset.peer === _fpeer && !el.dataset.done);
                // v3.4.82R（复核 P5）：走正式定格入口——清 unknown/stale
                //（「定格即清」不变量），不直写 dataset
                if (_fl) _hgPeerLineFreeze(_fl, '发送失败（Agent 不可恢复）');
              }
            }
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
          // v3.4.54：归属校验（防御性）——只定格本会话的线；异会话线直接
          // 丢弃跟踪（DOM 已随切场销毁）
          if (el.dataset.vsid !== (_HG.sid || ''))
            return;
          const vtxt = Array.isArray(tr.content)
            ? tr.content.filter(x => x && x.type === 'text').map(x => x.text).join('\n')
            : String(tr.content || '');
          // v3.4.88（识图卡化）：定格+全文入卡（点开见完整回传），气泡退役；
          // pw 摘还仅剩单槽兼容兜底路径在用
          const pw = _HG.peerWait;
          _HG.peerWait = null;
          _hgVisionResult(el, vtxt.trim() || '（识图失败，无返回内容）', !!tr.is_error);
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
        // v3.4.60：SubagentHandback 注入形态是「Another...sent a message:
        // <agent-message from="agentId">」——from-name= 提取不到名、body 落
        // 整段（含标签原文），renderPeer('其他会话') 按名配对恒 miss → 转交
        // 线永久「等待结论回传」（用户实锤「明明已完成还等协作回传」）。
        // 名字补 from= 提取；body 优先剥 agent-message 壳
        const nm = peerText.match(/from-name="([^"]*)"/) || peerText.match(/\bfrom="([^"]*)"/);
        // v3.4.68：from 命中本会话子代理档案=续派复核的回报——线已不建
        // （派发侧 _localResend），这里也不渲染不建段：renderPeer 冻结 miss
        // 后会走「miss 新建段」路径凭空冒协作段。报告本体主回合已消费，
        // 档案 brief 有摘要，无需再落可视化
        if (nm && nm[1] && Object.values(_HG.agents || {})
            .some(a => a && (a.agentId === nm[1] || a.taskId === nm[1])))
          return;
        const body = peerText.match(/<cross-session-message[^>]*>([\s\S]*)<\/cross-session-message>/)
          || peerText.match(/<agent-message[^>]*>([\s\S]*?)<\/agent-message>/);
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
        // v3.4.60：from= 属性形态（SubagentHandback）同链加固；from 系协议
        // 属性排在泛化 name= 之前（轻审P2：正文恰含 name="..." 时防抢跑错配）
        const anm = agMsg.match(/from-name="([^"]*)"/) || agMsg.match(/\bfrom="([^"]*)"/)
          || agMsg.match(/\bname="([^"]*)"/);
        const abody = agMsg.match(/<agent-message[^>]*>([\s\S]*?)<\/agent-message>/);
        renderPeer(anm ? anm[1] : '协作代理',
                   (abody ? abody[1] : agMsg.replace(/<[^>]+>/g, '')).trim());
        return;
      }
      // v3.3.2(D6)：机器注入的可见性——task-notification/system-reminder 在
      // live 侧此前静默丢弃（主流零锚点）。渲染弱化系统行入组（不切割回合、
      // 不渲染用户气泡）；完整开闭标签对才判（手打半个标签不误伤，v2.37R2 哲学）
      {
        const _snd = (typeof c0 === 'string') ? c0
          : (Array.isArray(c0) && !c0.some(b => b && b.type === 'tool_result')
             ? ((c0.find(b => b && b.type === 'text' && typeof b.text === 'string') || {}).text || '')
             : '');
        const _snT = String(_snd || '').trim();
        const _snKind = (/^<task-notification[^>]*>[\s\S]*<\/task-notification>$/.test(_snT) && 'task-notification')
          || (/^<system-reminder[^>]*>[\s\S]*<\/system-reminder>$/.test(_snT) && 'system-reminder') || '';
        if (_snKind) { renderSysNote(_snKind, _snT); return; }
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
      // v3.5.130（用户批注「大回合计时不变？子代理跑时不应收起」）：hold 期
      // 中间 result **不做回合收尾**——组保持展开、秒表继续走（子代理在飞
      // 也算本回合工作）、子代理不收尾不关窗；result 帧存档，真收尾
      //（turn_complete 事件）才执行完整收尾序列
      if (_HG.hold) {
        _HG.holdRes = { o,
                        durMs: (typeof o.duration_ms === 'number' ? o.duration_ms : 0),
                        ok: !(o.subtype && o.subtype !== 'success') };
        endThinking(); closeRun();
        setBusy(true);
        if (o.subtype && o.subtype !== 'success')
          renderRaw(`⚠ 回复异常结束：${o.subtype}${o.result ? ' — ' + String(o.result).slice(0, 200) : ''}`);
        refreshSessions();
        return;
      }
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
      // v3.3.7（P5 自愈）：回合终结——丢 input 的 bash 行从转写回填真命令
      try { _hgPatchMissingCmds(); } catch(_) {}
      // v3.5.239（用户实锤「流式期间没有、结束瞬间冒出=显示bug」）：回合
      // 摘要胶囊（🔍 查阅·N 命令）全链路退役——result 时刻的插入（本行）
      // 与方案B重渲后的补插均已撤；工具构成已由头部副位「N思考·M工具·K识图」
      // 承载，胶囊冗余
      // v3.5.222 方案B（用户拍板「大回合结束后重渲一次，最简单」）：回合
      // 终把流式残留形态替换为 hist 规整形态——延迟 400ms（定稿动画/摘要
      // 行先落，避免双闪）后 fetch 真源+窗口重渲一次做对（与切回重渲同
      // 渲染器同语义，keepDom 原子换入无白屏）；期间新回合开跑/busy 则让
      // 位（新回合的终局会再做）；滚动不强贴底（用户可能翻历史，stickBtm
      // 判据交由 _hgScrollBottom 内部语义）
      if (_HG.sid && typeof _histFetch === 'function') {
        const _sidB = _HG.sid;
        setTimeout(() => {
          if (_HG.sid !== _sidB) return;
          // A组G3：切回静默窗（5s）内跳过——SSE 重放的 result 帧同样走到
          // 这里，会在命中路整窗重渲之上再全量替换（v224「只留那一次」被
          // 击穿，每重放 result 一番 150-260ms 长任务+整屏换帧）
          if (Date.now() - (_HG.lastSwitchAt || 0) < 5000) return;
          // v3.5.229（用户实锤「方案B没落实」）：busy 判据改 fetch 回的后端
          // 真值——原读 _HG.busy 在回填竞态窗/hold 场景下恒 true → 早退 →
          // 回合终重渲永不执行=流式残留（如游离摘要行）不被规整化
          _histFetch(_sidB).then((_ok) => {
            if (!_ok || _HG.sid !== _sidB) return;
            if (_HG.fetchedBusy) return;   // 真在跑（含 hold）让位
            // v3.5.240 ①：方案B重渲同款——进行中识图卡摘下/回插
            var _liveVis2 = [];
            try {
              _hgFlow.querySelectorAll('.h-tool.h-vision:not([data-done]), .h-ask-rs').forEach(c => _liveVis2.push(c));
              // v3.5.259：ask 行记所属组序锚（同 12-sessions——回插按锚归位）
              _liveVis2.forEach(c => {
                if (!c.classList.contains('h-ask-rs')) return;
                const _gs = _hgFlow.querySelectorAll(':scope > .h-grp');
                const _pg = c.closest('.h-grp');
                c.dataset.hgGidx = _pg ? Array.prototype.indexOf.call(_gs, _pg) : -1;
                // v3.5.267（全审）：补稳定键——组末行 h-end 水位（组序锚在
                // 窗口起点移动>20 回合后错位，水位跨重渲稳定）
                // v3.5.268（复核严重项）：水位戳只写在组根自身（11-histcache
                // _last=flow 末子级=组根），querySelectorAll 只查后代永不
                // 匹配自身→恒 0 全堆首组；改读组根 dataset
                if (_pg) c.dataset.hgGend = String(+(_pg.dataset.hEnd || 0));
              });
              _liveVis2.forEach(c => c.remove());
            } catch (_) {}   // v3.5.242：ask结果行同护
            try {
              _histRender(_HG.histAll, _HG.histStart | 0);
              // v3.5.235（用户实锤「流式时从没有过头+查阅胶囊,结束反而冒出
              // 来=不符合正常输出格式」）：方案B 重渲用的是 hist 渲染器——
              // 它给每个定稿组亮「已工作 X」头,这是**历史回放形态**;live
              // 会话刚结束的尾组应保持 live 干净形态（无定稿头无摘要行,
              // 正文+回滚按钮收尾）——重渲后对尾组隐藏头+删 turnsum+
              // 展开工作区。历史形态留给切回/只读场景（那时是历史语境）
              try {
                // v3.5.236（修正 v3.5.235 的悬空 bug）：头**保留**——live 流式
                // 定稿本来就有「已工作 X」头（grpFinalize 冻结，用户从未异议），
                // v3.5.235 把头 display:none 后工作区元素（缩进竖线/查阅行）失去
                // 容器悬空；只删尾组 turnsum 胶囊（用户实锤「流式期间没有、结束
                // 冒出来的只有这个」）+工作区展开（live 终态不折叠）
                const _gs = _hgFlow.querySelectorAll(':scope > .h-grp');
                const _lg = _gs[_gs.length - 1];
                if (_lg) {
                  _lg.querySelectorAll('.h-turnsum').forEach(x => x.remove());
                  // v3.5.239：turnsum 全链路退役后此删除仅兜底（旧会话快照
                  // 里可能残留历史胶囊）；其余行为一律保持渲染器原生
                }
              } catch (_) {}

              // A组S3a：任务卡不在转写——重渲整替会抹掉运行中任务卡，
              // 从 tasksBy 回填（与切换命中路同款；agents restore 同补）
              if (_HG.tasksBy && _HG.tasksBy[_sidB]) {
                const _tk2 = _HG.tasksBy[_sidB];
                for (const k in _tk2) {
                  const t2 = _tk2[k];
                  if (_hgFlow.querySelector('.h-taskcard[data-tid="' + k + '"]')) continue;
                  try { _taskStart(k, t2.desc || '');
                    const nt = (_HG.tasks || {})[k];
                    if (nt) Object.assign(nt, t2, { el: nt.el });
                  } catch (_) {}
                }
              }
              if (typeof _hgLiveAgentsRestore === 'function') { try { _hgLiveAgentsRestore(_sidB); } catch (_) {} }
              try {
                const _gsV2 = _hgFlow.querySelectorAll(':scope > .h-grp');
                const _lgV2 = _gsV2[_gsV2.length - 1];
                const _tlV2 = _lgV2 && _lgV2.querySelector('.h-tl');
                _liveVis2.forEach(c => {
                  // v3.5.259：ask 行按组序锚归位（同 12-sessions）
                  if (c.classList.contains('h-ask-rs') && c.dataset.hgGidx != null) {
                    const _gsA = _hgFlow.querySelectorAll(':scope > .h-grp');
                    // v3.5.267（全审）：优先按组末行水位精确匹配（稳定键），
                    // 组序锚仅兜底（窗口移动后序错位），越界终兜底尾组
                    let _tg = null;
                    const _ge = c.dataset.hgGend;
                    // v3.5.268：读组根自身戳（'0'=无戳组不参与匹配）
                    if (_ge && _ge !== '0') {
                      for (const gg of _gsA) {
                        if (String(+(gg.dataset.hEnd || 0)) === _ge) { _tg = gg; break; }
                      }
                    }
                    if (!_tg) {
                      const _gi = +c.dataset.hgGidx;
                      if (_gi >= 0 && _gi < _gsA.length) _tg = _gsA[_gi];
                    }
                    if (!_tg) _tg = _gsA[_gsA.length - 1];
                    const _ttA = _tg && _tg.querySelector('.h-tl');
                    if (_ttA) { _ttA.appendChild(c); return; }
                  }
                  if (_tlV2) _tlV2.appendChild(c);
                  if (c.dataset.tid) {
                    _HG.visionCalls = _HG.visionCalls || {};
                    _HG.visionCalls[c.dataset.tid] = c;
                    try { _hgPeerTimerStart(c, +(c.dataset.t0 || 0) || Date.now()); } catch (_) {}
                  }
                });
              } catch (_) {}
              _hgScrollBottom();
            } catch (_) {}
          });
        }, 400);
      }
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
  function _hgSseResetLocal(keepDom) {
    _HG.fetchedBusy = null;   // C组T5：随清场清（防陈旧值误用）
    // 清场：内存态与 DOM 全部作废（switchTo 的重置块同款，供 snapshot/reset 用）
    // v3.5.196：keepDom=true 时跳过 flow 清空（reload 重建用）——旧 DOM 保留
    // 到渲染器原子换入，消除「清场→新内容换入」之间的白屏空窗（用户实锤
    // 「连着两个 300ms 空闲帧=体感卡顿」：原清场先清 DOM 再等 fetch+渲染）
    // v3.5.123：hold 旗随清场（切走的会话若在 hold，回切由 replay 的 turn_hold 重建）
    _HG.hold = false;
    endThinking(); closeRun();
    // v3.4.55（轻审 P4）：清 agents 前运行档案入桶——reset/快照重建路
    // 同样暂存（switchTo 同款判据），重建完成后 _hgLiveAgentsRestore 回填
    if (_HG.agents && _HG.sid) {
      _HG.liveAgentsBy = _HG.liveAgentsBy || {};
      const _tgt = (_HG.liveAgentsBy[_HG.sid] = _HG.liveAgentsBy[_HG.sid] || {});
      for (const t in _HG.agents) {
        const a = _HG.agents[t];
        if (a && !a.done && (!a.sid || a.sid === _HG.sid)) _tgt[t] = a;
      }
    }
    if (_HG.grp) phStopTimer(_HG.grp);
    _turnHeadStop();   // v3.2：回合秒表随清场全收（timer 不随 innerHTML 快照走，不收就漏）
    Object.values(_HG.subBlk || {}).forEach(b => { if (b && b.timer) clearInterval(b.timer); });
    _HG.rowById = {}; _HG.uidN = 0; _HG.run = null; _HG.grp = null; _HG.histNav = null;
    _HG.subRows = {}; _HG.subBlk = {}; _HG.subTail = {}; _HG.subTailSeg = {};
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false; _HG.histStale = false;
    _HG.archivedTurns = 0;   // v3.5.61：归档轮数随清场归零（切会话由 hist 重算）
    _HG.todos = null; _HG.agents = null; _HG.dyn = null;
    // v3.4.54：识图 pending 线随清场收（switchTo 重置块同款——两处必须同步）
    Object.values(_HG.visionCalls || {}).forEach(_hgPeerLineStop);
    _HG.visionCalls = null;
    _HG.proj = null;   // v3.1：投影随清场作废（snapshot 重放将重建）
    _subReset();
    _HG.think = null; _HG.noScroll = false; _HG.openState = null;
    _HG.stickBtm = true;   // v3.4.67：粘底跟读态随清场复位（重建后默认贴底）
    _HG.histLineTs = 0; _HG.histActTs = 0; _HG.thinkPend = null;   // v3.2.2 ts 账 + v3.2.5 pend 随清场作废
    _HG.prevRowAt = 0; _HG.lastRowAt = 0;   // v3.3.1(F5)：事件时刻账随清场作废
    _HG.echoFast = null; _HG.seq = 0;
    if (!keepDom) _hgFlow.innerHTML = '';
    _hgRailSync();   // v3.2.10：本地清场后收轨（keepDom 时轨随渲染器换入后同步）
  }
  function _hgSseRebuild(sid) {
    // reset 语义：事件流已无法表达真源（/rewind 换代）→ 弃快照缓存走
    // transcript 重建（switchTo 无缓存分支同款），完成后以新水位重开流。
    if (_HG.sse) { try { _HG.sse.close(); } catch(_) {} _HG.sse = null; }
    if (!sid || sid !== _HG.sid) return;
    delete _HG.cache[sid];
    _hgSseResetLocal();
    _HG.histRebuilding = sid;    // 轻审 P2：清场→重建的 await 窗口期 saveCache
                                 // 不得入库（空 flow 快照击穿 delete）。
                                 // 复审 P3：值=sid 按归属自清——清点不吃当前
                                 // _HG.sid（切走后迟到的 finally 也要清，否则
                                 // 标志永久搁浅、所有快照静默失效）
    setBusy(false);
    fetch(`/api/harness/transcript?sid=${encodeURIComponent(sid)}`)
      .then(r => r.json())
      .then(j => {
        if (!j.ok || _HG.sid !== sid) return;
        _HG.seq = j.seq || 0; _HG.epoch = j.epoch || null; _HG.alive = !!j.alive;
        if (!j.lines.length) showWelcome();
        else _histRender(j.lines, _hgHistWinStart(j.lines),
                         { noFinalize: !!j.busy });   // v3.2.1R(F1)：尾组定稿在渲染器内；busy 活组留给 phResume
        if (j.busy) phResume(true); else grpFinalize(true, { hist: true, turnEnd: true });   // 幂等兜底（v3.2R1(P0)：回放不吃时钟；v3.2.4R(F5) 对齐 switchTo turnEnd）
        _hgLiveAgentsRestore(sid);   // v3.4.55（轻审 P4）：reset 重建路同样回填运行中子代理
        _hgAskSync(sid);   // v3.4.61：重建路 seq 已跳过 ask 帧——待答面板靠后端快照拉回
        _hgScrollBottom(true);
        setBusy(!!j.busy, j.busy_since);   // v3.4.71：旧序恢复（phResume 已带参先行），活动条/发送键态回填
        openSSE(sid, _HG.seq);
        refreshSessions();
        // v3.4.68R3：reset 重建出口同挂覆盖度自检（openSSE 之后 2s=尘埃落定，
        // snapshot 清场若再吞成果由审计兜住）
        setTimeout(() => _hgCoverageAudit(sid, j.lines.length, 'sse-rebuild'), 2000);
        _hgDiag('rebuild', 'reset 重建完成 lines=' + j.lines.length + ' busy=' + !!j.busy);
      })
      .catch(() => {})
      .finally(() => { if (_HG.histRebuilding === sid) _HG.histRebuilding = null; });
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
      // 事件顺序保证清场时机正确）。复审 P4：清场→首帧重放的间隙也是
      // 「空 flow + saveCache」窗口——同置重建标志，首帧到达即清
      if (a.mode === 'snapshot') {
        // v3.5.77（用户实锤「新会话首条消息消失」）：冷启动竞态——openSSE(0)
        // 的 ack(snapshot) 在乐观渲染之后到达时，清场（resetLocal）把刚画的
        // 用户气泡抹掉；此刻保留窗为空（消息尚未 POST /send 或刚入窗），
        // 重放救不回、echoFast 又让随后 user_echo 跳过补画 = 首条消息蒸发
        // （切 B 再切回靠转写重渲才回来）。守卫：转写渲染未建（histAll 空）且
        // 乐观气泡在场——无任何可重放基线，不清场（活视图即最新态；已流过
        // 的帧由 seq 去重天然免疫重放）
        if (!_HG.histAll && _HG.echoFast) {
          _hgDiag('sse', 'ack=snapshot 跳过清场（新会话乐观气泡在场）');
          return;
        }
        _hgDiag('sse', 'ack=snapshot 清场重放（histAll=' + (((_HG.histAll)||[]).length) + '）');
        // v3.4.68R3：清场前抢存转写行数基准（resetLocal 会清 histAll）——
        // 重放落定后跑覆盖度自检，缺口大即整帧重渲自愈（用户实锤「切回后
        // 工作中的显示全没了等很多秒不复原」——保留窗若不含清场前内容，
        // 重放救不回，此审计是最后防线）
        const _snapBase = (_HG.histAll || []).length;
        _hgSseResetLocal();
        _HG.histRebuilding = sid;
        const _hbrSid = sid;
        setTimeout(() => { if (_HG.histRebuilding === _hbrSid) _HG.histRebuilding = null; }, 1500);
        setTimeout(() => _hgCoverageAudit(sid, _snapBase, 'sse-snapshot',
          { snapshotBase: true }), 2000);
        _hgBusyResync(sid, 2100);   // v3.4.69d：清场重放落定后 busy 会话无条件重渲兜底
      }
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
      // v3.3.1：事件到达时刻账——prevRowAt=上一事件时刻（lastRowAt 尚未翻转）。
      // 思考段时长的挂钟基准：think 与同消息 tool_use 同批到达，按本事件时刻
      // 计时长恒 0 秒（用户实锤）；上一事件时刻≈真实思考/API 等待期。重放帧
      //（seq 未过）不更新——重放不产生挂钟事实
      _HG.prevRowAt = +(_HG.lastRowAt || 0) || 0;
      _HG.lastRowAt = Date.now();
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
        // v3.5.77：跳过的前提=乐观气泡还在屏（el.isConnected）——气泡若被
        // 中途清场（快照重放/重建竞态）抹掉，echo 负责补画（防蒸发兜底）
        if (_HG.echoFast && _HG.echoFast.text === (it.text || '')) {
          const _live = _HG.echoFast.el && _HG.echoFast.el.isConnected;
          _HG.echoFast = null;
          if (!_live && !_hgEchoDup(it)) renderUser(it.text, it.images, it.files);
        }
        else if (!_hgEchoDup(it)) renderUser(it.text, it.images, it.files);
      }
      else if (it.kind === 'event') {
        // v3.5.293（用户实锤内网「停止超长回合后发新消息前端冻结」）：单事件
        // 异常隔离——handleEvent 内任何一步抛异常此前会沿 onmessage 冒出，
        // EventSource 消息处理终止=后续所有事件全丢（旧秒表转/新消息不渲染，
        // 心跳照收看门狗不触发），直到切会话 transcript 重建才恢复。隔离后
        // 单事件炸只丢该事件并 console.error 留证（kind/seq/堆栈），事件流
        // 永不断——无论内部还有什么渲染 bug，都不再冻结整个前端
        try { handleEvent(it.data); }
        catch (e) { try { console.error('[sse] 事件处理异常 kind='
          + ((it.data && it.data.kind) || '?') + ' seq=' + it.seq, e); } catch(_) {} }
      }
      // v3.3.2(D4)：协作回传不切割回合（renderPeer v3.2.15 注释的既定意图，
      // 分派处 grpFinalize 是残留矛盾）——先重开上一回合再渲染，回传唤醒的
      // 续跑工作才落回原组；空闲期回传是 P7 主场景
      else if (it.kind === 'peer') { _hgTurnReopen(true); renderPeer(it.name, it.text, it.to); }
      // v3.5.123（用户口径「子代理在飞不许结束大回合」）：后端 hold 保活事件
      else if (it.kind === 'turn_hold') {
        _HG.hold = true;
        setBusy(true);   // 幂等保持工作中（输入走排队，子代理全完成后泵出）
      }
      else if (it.kind === 'turn_complete') {
        // v3.5.130：真收尾——补完整回合收尾序列（hold 期中间 result 跳过的
        // 那套，此刻用存档的 result 帧数据执行：子代理收尾/窗格收起/组定稿
        // 收起/秒表定格冻结工时/ctx 环/回滚授予）
        _HG.hold = false;
        const hr = _HG.holdRes || {}; _HG.holdRes = null;
        _hgVisionSweep(true);
        _hgAgentsSweep(false, true);   // v3.5.143：force 收 bg 残留（notification 丢失/后端硬顶释放后卡片不死跑）
        _subEnd();
        _hgPeerVerifyPending();
        _hgTurnEnd(hr.ok === false ? 'error' : 'ok', hr.durMs || 0);
        try { _hgPatchMissingCmds(); } catch (_) {}
        grpFinalize(true, { durMs: hr.durMs || 0,
                            interrupted: hr.ok === false,
                            hist: _hgTailAdopt(),
                            turnEnd: true });
        _hgGrantRewind();
        if (hr.o) renderCtxRing(hr.o);
        setBusy(false);   // 真收尾（bg 集空后的唤醒回合 result）——正常落 busy
        refreshSessions();
      }
      // v3.5.183：subagent_slow 前端提示退役（用户定调「提示全部去掉，没用」）——
      // 探活对内进行（CLI 进程+转写活跃度，30/45/60 分级），结论走工作区审计卡
      else if (it.kind === 'renew') { grpFinalize(true); renderRenew(it.text); }
      // v2.34：审计警示（light 回合结算违规）——回合已终结，定稿当前组再出红卡
      else if (it.kind === 'audit') { renderAudit(it.text); _hgScrollBottom(); }   // v3.2.27：撤 grpFinalize——警示入工作区不分割回合
      else if (it.kind === 'raw') renderRaw(it.text);
      // v3.3.2(B/D3)：ask 不定稿——提问是当前工作状态的中途暂停（CLI 同回合
      // 阻塞），答后续跑 grpEnsure 自然回原组；v3.4.61 面板入输入框上方 dock
      //（askRender 内），占位气泡让位（等答面板即占位）
      else if (it.kind === 'ask') { const _g = _hgTurnReopen(); phRemove(_g || _HG.grp); askRender(it); }
      else if (it.kind === 'ask_done') askDone(it);
      else if (it.kind === 'interrupted') {
        _HG.hold = false;   // v3.5.124：中断/退出=保活退场（防旗残留瞬态误态）
        endThinking(); _hgVisionSweep(true);
        // v3.4.79（用户定调「中断行整合进回合」）：exit 行先入组时间线再定稿
        // ——先定稿的话 _HG.grp 已收，行散落组外（点开回合看不到中断实况）。
        // v3.4.79R（复核 R2/R4）：stopGen 本地收尾的迟到回执走轻收尾——判据
        // 加 !_HG.grp（本地收尾后 grp 必 null；新回合真帧到达时 grp 活，
        // 5s 内二次中断不被误吞）+ sid 归属；命中则整段跳过（含 turnEnd
        // 双记），只通知 stopGen「事件到了」
        if (it.text === '已中断回复' && !_HG.grp
            && Date.now() - (_HG._stopLocalAt || 0) < 5000
            && _HG._stopLocalSid === _HG.sid) {
          try { document.dispatchEvent(new CustomEvent('hg-interrupted', {detail: _HG.sid})); } catch(_) {}
          setBusy(false);   // 复核 F-A：幂等兜底——真帧被闸吞时 busy 不依赖后续 exit 帧
          return;
        }
        renderExit(it.text);
        // v3.4.84（用户实锤「还是显示工作中」）：exit 帧先到时它已把 _HG.grp
        // 收走（置 null）——迟到的 interrupted 帧 grpFinalize 在 !g 早退，头
        // 定稿块（含 v3.4.80 的 interrupted 无条件翻头）根本没机会跑=头永挂
        // 「工作中 Ns」。兜底：组失联时直接翻尾组头文案（时长段保留）
        if (!_HG.grp) {
          const _tg = [..._hgFlow.querySelectorAll('.h-grp')].pop();
          const _tlbl = _tg && _tg.querySelector('.h-turn-label');
          // 复核残留 b 收口：exit 先到写的「已工作」也翻「已停止」（中断语义
          // 不丢）；「已停止」幂等不碰
          if (_tlbl && (_tlbl.textContent.indexOf('工作中') === 0
                        || _tlbl.textContent.indexOf('已工作') === 0))
            _tlbl.textContent = _tlbl.textContent.replace(/^(工作中|已工作)/, '已停止');
        }
        grpFinalize(true, { interrupted: true, hist: _hgTailAdopt(), turnEnd: true });   // v3.2.1R2(R2-1/R2-3)认回；v3.2.2 中断=回合收尾，正文留头外
        // v3.4.61：中断即提问失效（后端 ask_cancel 不发帧——面板不再空挂）
        _hgAskDismiss(_hgAskDockEl && _hgAskDockEl.querySelector('.h-ask:not(.done)'),
                      '已随会话中断失效');
        setBusy(false);
        // v2.32：中断收尾——在跑的子代理标「已中断」（原缺口：只有 result
        // 分支收尾，点 ■ 停止后子代理假"运行中"+计时狂跳）
        _hgAgentsSweep(true); _hgTurnEnd('interrupt', 0);
        _subEnd();                         // v2.33：窗格收起
        // v2.15：通知 stopGen 兜底逻辑「事件到了」，别重复收尾
        try { document.dispatchEvent(new CustomEvent('hg-interrupted', {detail: _HG.sid})); } catch(_) {}
      }
      else if (it.kind === 'exit') {
        _HG.hold = false;   // v3.5.124：中断/退出=保活退场（防旗残留瞬态误态）
        endThinking(); _hgVisionSweep(true); _HG.alive = false;
        // v3.4.79：exit 行先入组再定稿（同 interrupted 分支——组外散行整合）
        renderExit(it.text);
        grpFinalize(true, { hist: _hgTailAdopt(), turnEnd: true });   // v3.2.1R2(R2-1)认回；v3.2.2 退出=回合收尾，正文留头外
        _hgAskDismiss(_hgAskDockEl && _hgAskDockEl.querySelector('.h-ask:not(.done)'),
                      '已随会话结束失效');   // v3.4.61：进程退出=提问失效，面板收缩
        setBusy(false);
        _hgAgentsSweep(true); _hgTurnEnd('exit', 0);   // v2.32：同上，进程退出也收
        // v3.5.22：后台任务全定格「已中断」（进程没了，CLI 侧后台 shell 同亡）
        Object.keys(_HG.tasks || {}).forEach(_tk => {
          const _tt = _HG.tasks[_tk];
          if (!_tt.done) _taskFinish(_tk, 'stop', '会话进程已退出');
        });
        _subEnd();                         // v2.33：窗格收起
      }
      // v2.20：会话内切模型 → 消息流插一条分割线（「已切换模型 · xxx」）
      else if (it.kind === 'model_switched') {
        grpFinalize(true, { turnEnd: true });   // v3.2.2：切模型发生在回合间，正文留头外
        renderSwitch(it.text || '默认模型');
        // v3.5.43：切模型=识图形态可能翻转（inline↔mcp）——徽章即刻刷
        // （进程重启重建 mcp-config，vision_status 按 sid 现算新形态）
        if (typeof paintVisionBtn === 'function') paintVisionBtn();
        // v3.5.96（用户实锤「同会话切 glm-5.3，消息徽章仍显示轻主力」）：
        // 角色徽章读 _hgRolesCache，切会话/开面板都会刷、唯独切模型不刷
        // ——轻↔重翻转后新消息仍盖旧形态章（三角色面板现拉所以显示对）
        if (typeof _hgRolesFetch === 'function') _hgRolesFetch();
      }
    };
  }
  function _hgHasHistory(sid) {
    const s = _HG.sessions.find(x => x.sid === sid);
    return !!(s && s.has_history);
  }
  function saveCache() {
    // v3.5.51（designer B2）：只读模式防毒化——RO 渲染的是目标会话 DOM，
    // 此刻入库会把 B 的内容写进 A(_HG.sid) 的快照；RO 中关页/切换路径防御
    if (_HG.readonly) return;
    if (!_HG.sid) return;
    // 轻审 P2（v3.4.60）：重建窗口期（_hgSseRebuild/_hgReloadFlow 清场后
    // transcript fetch 在途）不入库——此刻 flow 是空/残的，且重建入口的
    // delete cache 会被这次入库击穿，切回恢复出空白工作区。
    // 复审 P3：门按「本会话」判——别会话在途的重建不拦本会话存快照
    if (_HG.histRebuilding && _HG.histRebuilding === _HG.sid) return;
    // v2.28.13：echoFast 随快照保存——切走时 2420 行会清空它，但快照 html
    // 里已经带着乐观渲染的用户气泡；若 user_echo 尚未到达（快速切走），
    // 切回来重放的 echo 对不上已清空的去重窗口 → 双画（用户实锤 A→B→A
    // 出两条同文消息）。随快照存取，恢复后重放 echo 仍能命中跳过。
    // v2.37（P0-A）：窗口账目随快照存——恢复路径重建 histStart/histLive，
    // 使滚动扩收机制在快照态重新成立（此前快照恢复后 histLive=false 且
    // histStart 丢失，上滑扩段被 v2.35.2 的门拦死，历史够不着）
    _HG.cache[_HG.sid] = { html: _hgFlow.innerHTML, seq: _HG.seq,
                           epoch: _HG.epoch || null,
                           // v3.4.61：dock 待答面板随快照走（dock 在 flow 外不吃
                           // innerHTML）——只存 pending（done 面板收缩即逝）；切回
                           // 由 _hgAskDockRestore 回挂，豁免判定（12-sessions）同源
                           askPanel: (_hgAskDockEl
                             && _hgAskDockEl.querySelector('.h-ask:not(.done)') || {}).outerHTML || '',
                           // v3.0 滚动记忆（对照 ZCode chatSessionScrollMemory 五元组）：
                           // 贴底记忆→切回回底（跟读新消息）；否则恢复钳制后的
                           // scrollTop——翻历史中途切走再切回，视口不再被拽到底
                           // v3.4.68（用户实锤「每次重开都不是直达底部的」）：
                           // atBottom 改用粘底标志——isNearBottom() 是切走瞬间的
                           // 单点采样，流式输出撑高 flow 时必失真（贴底跟读也被
                           // 记成「在看历史」，切回永远停半空）。stickBtm 只在
                           // 用户真上翻（gap>150）才 false，语义即「是否跟读」
                           scroll: { top: _hgFlow.scrollTop, h: _hgFlow.scrollHeight,
                                     ch: _hgFlow.clientHeight, atBottom: _HG.stickBtm !== false },
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
                             // v3.4.60（用户实锤「切回只剩我的消息+转圈，已工作
                             // 全无，新消息来了才刷出」）：空 flow（rebuild 中间态
                             // /重置后未重建）与 histStale 降级态（已确认账目漂移）
                             // 的快照注定残缺——旧判定「无组=false」把它们当完整
                             // 快照入库，恢复端先渲残缺再等异步自愈
                             if (!g) return !!(_HG.busy || _HG.histStale
                                 || (_HG.histAll && _HG.histAll.length));
                             return g.dataset.finalized !== '1';
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
        if (j.busy) phResume(true);
      })
      .catch(() => { if (_HG.sid === sid) setBusy(false); });
  }
