// harness fev.js (R0 起：FEV 事件模型 + user 行过滤单一实现)
  // ==================== FEV——前端统一事件模型（ZCode SessionEvent 对位）====================
  // 设计定调：live 与冷读两源归一成同一 FEV 事件 → 同一 reducer（23-reducer
  // _HG_REDUCERS handlers map）→ 同一投影 → 同一渲染订阅（27-store
  // _hgRenderEntries）。事件为平对象 { t: <事件名>, ...payload }，live/hist
  // 两轨在各分支手工构造（比 adapter 转换层更直白——R7 大扫除实证：
  // _fevFromLive/_fevFromHistLine 零外部引用，adapter 层删除）。
  //
  // 事件目录（JSDoc 契约——handlers 键全集）：
  //   回合： turn_started turn_complete{ok,durMs,usage,subtype,frame}
  //         turn_error turn_interrupted{text,hist} turn_exit{text,hist}
  //         turn_hold model_switched{name} compact_started compact_end
  //   消息： user_message{text,images,files,ts} assistant_text{text,model}
  //         assistant_thinking{text,hi,ts,prevTs,live}
  //   工具： tool_call_started{id,name,input} tool_call_result{id,out,err}
  //   协作： peer_relay peer_return{name,text,to,tid,hist|live}
  //         peer_sent{tid,to,msg1}
  //   杂项： sysnote{kind,text} audit{text} raw{text} renew{text}
  //   提问： ask{req_id,title,questions} ask_done{req_id,answer}
  //   队列： input_admitted input_promoted input_discarded
  //   子代理域（25-registry 冷查询域，不进 handlers）：task_started†
  //         task_notification† subagent_started† subagent_result†

  // ---- user 行过滤规则（单一实现——live user_echo 与 hist role:user 共用）----
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
