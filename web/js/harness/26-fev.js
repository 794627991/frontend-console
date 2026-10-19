// harness fev.js (R0 流式/重渲统一管线：FEV 事件信封 + 两源 adapter)
  // ==================== FEV——前端统一事件模型（ZCode SessionEvent 对位）====================
  // 设计定调（designer 聚焦方案，用户红线=UI 风格不变）：live 与冷读两源
  // 各自经纯函数 adapter 归一成同一 FEV 序列 → 同一 reducer → 同一投影 →
  // 同一套渲染函数。事件模型为规范形（live 帧天然事件含进行态；行是已
  // 归约快照，反向展开规则=tool 行一拆二）。本文件零 DOM、零 _HG 写。
  //
  // FEV = 平对象 { t: <事件名>, ...payload }。目录（JSDoc 契约）：
  //   回合： turn_started{ts} turn_complete{ok,durMs,usage,subtype}
  //         turn_error{text} turn_interrupted{text} turn_exit{text} turn_hold{}
  //   消息： user_message{text,images,files,ts,id?} assistant_text{text,model,ts}
  //         assistant_thinking{text,ts}
  //   工具： tool_call_started{id,name,input,ts,parentTid?}
  //         tool_call_result{id,out,summary,err,ts,dln?}
  //   识图： vision_call{id,name,input,chan,ts} vision_result{id,text,err}
  //   协作： peer_relay{to,tid,ts} peer_return{name,text,to?}
  //         peer_sent{tid,to,msg1}
  //   杂项： sysnote{kind,text} audit{text} raw{text} renew{text}
  //         model_switched{name} compact_started{} compact_end{}
  //   队列： input_admitted{id,text,att} input_promoted{id} input_discarded{id,reason}
  //   子代理域（†形态登记，本期不收编——25-registry 单点纪律域）：
  //         task_started† task_notification† subagent_started† subagent_result†
  //         subagent_message{agentId,blocks}†
  const _FEV = {};
  ['turn_started', 'turn_complete', 'turn_error', 'turn_interrupted',
   'turn_exit', 'turn_hold', 'user_message', 'assistant_text',
   'assistant_thinking', 'tool_call_started', 'tool_call_result',
   'vision_call', 'vision_result', 'peer_relay', 'peer_return',
   'peer_sent', 'sysnote', 'audit', 'raw', 'renew', 'model_switched',
   'compact_started', 'compact_end', 'input_admitted', 'input_promoted',
   'input_discarded'].forEach(t => { _FEV[t] = t; });

  // ---- liveAdapter：SSE 帧/信封 → FEV 列表（纯函数）----
  function _fevFromLive(o) {
    // o = openSSE.onmessage 的信封 {kind, data, ...}（kind 信封=后端 emit 的
    // 干净事件直通；data=原始 CLI stream-json 帧）。返回 FEV 数组（一帧可
    // 产多事件：assistant content 循环）。
    const out = [];
    if (!o || typeof o !== 'object') return out;
    const k = o.kind || o.type;
    if (k === 'cli_stream') {
      const d = o.data || {};
      const ts = d.timestamp || '';
      const typ = d.type;
      if (typ === 'system') {
        if (d.subtype === 'status' && /compacting/i.test(String(d.status || '')))
          out.push({ t: _FEV.compact_started, ts });
        return out;   // 其余 system 帧（init/task_*）归传输层/子代理域†
      }
      if (typ === 'assistant') {
        const c = (d.message || {}).content;
        if (!Array.isArray(c)) return out;
        for (const b of c) {
          if (!b || typeof b !== 'object') continue;
          if (b.type === 'thinking')
            out.push({ t: _FEV.assistant_thinking, text: String(b.thinking || ''), ts });
          else if (b.type === 'text')
            out.push({ t: _FEV.assistant_text, text: String(b.text || ''),
                       model: (d.message || {}).model || '', ts });
          else if (b.type === 'tool_use') {
            const inp = b.input || {};
            const nm = String(b.name || '');
            if (_HG_IS_VISION_TOOL(nm))
              out.push({ t: _FEV.vision_call, id: String(b.id || ''), name: nm,
                         input: inp, chan: String(inp.chan || inp.channel || ''),
                         ts });
            else
              out.push({ t: _FEV.tool_call_started, id: String(b.id || ''),
                         name: nm, input: inp, ts,
                         parentTid: String(d.parent_tool_use_id || '') || undefined });
          }
        }
        return out;
      }
      if (typ === 'user') {
        const c = (d.message || {}).content;
        if (!Array.isArray(c)) {
          // 纯文本 user 帧（peer 回传/系统注入）由 kind 信封路径处理
          return out;
        }
        for (const b of c) {
          if (!b || typeof b !== 'object') continue;
          if (b.type === 'tool_result') {
            const tid = String(b.tool_use_id || '');
            const txt = (typeof b.content === 'string') ? b.content
              : (Array.isArray(b.content)
                 ? b.content.filter(x => x && typeof x === 'object')
                     .map(x => String(x.text || '')).join('\n') : '');
            out.push({ t: _FEV.tool_call_result, id: tid, out: txt,
                       err: !!b.is_error, ts });
          }
        }
        return out;
      }
      if (typ === 'result') {
        out.push({ t: _FEV.turn_complete, ok: !d.is_error,
                   durMs: d.duration_ms || 0, usage: d.usage || null,
                   subtype: String(d.subtype || ''), ts });
      }
      return out;
    }
    // kind 信封直通（后端 emit 的干净事件——与 FEV 同名映射）
    const _map = {
      peer: 'peer_return', ask: 'ask', audit: 'audit', raw: 'raw',
      renew: 'renew', interrupted: 'turn_interrupted', exit: 'turn_exit',
      model_switched: 'model_switched', turn_hold: 'turn_hold',
      user_echo: 'user_message', subagent_started: 'subagent_started',
      subagent_result: 'subagent_result',
      input_admitted: 'input_admitted', input_promoted: 'input_promoted',
      input_discarded: 'input_discarded',
    };
    const fevt = _map[k];
    if (fevt) {
      const ev = { t: fevt };
      for (const kk of ['id', 'text', 'to', 'name', 'tid', 'aid', 'att',
                        'reason', 'images', 'files', 'agent_type', 'desc',
                        'bg', 'task_id', 'tokens', 'tool_n', 'ok', 'brief'])
        if (o[kk] !== undefined) ev[kk] = o[kk];
      out.push(ev);
    }
    return out;
  }
  // 识图工具名判定（与 06-relay/08-tools 现行口径一致的最小集——R4 收编
  // 时统一为单一常量源；R0 骨架期保守内联）
  function _HG_IS_VISION_TOOL(nm) {
    return /^(mcp__vision__analyze_image|mcp__4_5v_mcp__analyze_image|analyze_image)$/i.test(String(nm || ''));
  }

  // ---- R2b：user 行过滤规则（单一实现——live user_echo 与 hist role:user
  //      两轨此前各持一份同款过滤，屎山点收敛处）。返回 {text, skip} ----
  function _fevUserFilter(text, files) {
    // ① 贴图占位回显（v3.2.16 定调）：CLI 对每次贴图落两条 user 行（真图
    // 缩略 + "[Image: source: 路径]" 纯回显）——回显标记一律剥掉、路径不
    // 并入附件；剥完空壳（无文字无他附件）整条不渲染
    let t = String(text || '');
    const _ims = t.match(/\[Image: source: [^\]]+?\]/g);
    if (_ims) {
      t = t.replace(/\[Image: source: [^\]]+?\]/g, '').trim();
      if (!t && !(files || []).length) return { text: '', skip: true };
    }
    // ② 中断/续跑机器标记行（v3.2.12）：非用户输入，整条不渲染
    if (/^(\[Request interrupted by user( for tool use)?\]|Continue from where you left off\.)/i.test(t.trim()))
      return { text: t, skip: true };
    return { text: t, skip: false };
  }

  // ---- coldAdapter：transcript 行 → FEV 列表（纯函数，R1 起逐域接线）----
  function _fevFromHistLine(l) {
    // l = transcript_for 产出行 {role, ...}。role→FEV 映射；tool 行一拆二。
    const out = [];
    if (!l || typeof l !== 'object') return out;
    const ts = l.ts || '';
    switch (l.role) {
      case 'user':
        out.push({ t: _FEV.user_message, text: String(l.text || ''),
                   images: l.imgs || [], files: l.files || [], ts });
        break;
      case 'assistant':
        out.push({ t: _FEV.assistant_text, text: String(l.text || ''),
                   model: String(l.model || ''), ts });
        break;
      case 'thinking':
        out.push({ t: _FEV.assistant_thinking, text: String(l.text || ''), ts });
        break;
      case 'tool': {
        const nm = String(l.text || '');
        const ts2 = ts || 0;
        out.push({ t: _FEV.tool_call_started, id: String(l.id || ''),
                   name: nm, input: l.input || {}, ts: ts2 });
        out.push({ t: _FEV.tool_call_result, id: String(l.id || ''),
                   out: String(l.result || ''), summary: String(l.summary || ''),
                   err: !!l.err, ts: ts2, dln: l.dln });
        break;
      }
      case 'peer':
        out.push({ t: _FEV.peer_return, name: String(l.name || ''),
                   text: String(l.text || ''), to: l.to, ts });
        break;
      case 'sysnote':
        out.push({ t: _FEV.sysnote, kind: String(l.sub || ''), text: String(l.text || ''), ts });
        break;
      case 'renew':
        out.push({ t: _FEV.renew, text: String(l.text || ''), ts });
        break;
      default:
        break;   // sub_*（子代理域†）/分组行等：R1+ 逐域接线
    }
    return out;
  }
