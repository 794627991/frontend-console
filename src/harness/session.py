# -*- coding: utf-8 -*-
"""harness.session —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import base64
import json
import os
import re
import subprocess
import threading
import time
import logging
log = logging.getLogger(__name__)
from ..claude_conn import _resolve_claude_exe, _trust_workspace
from .roles import audit_verdict, design_limit, install_roles_agents, roles_bridge_text
from .askmcp import _ask_mcp_cfg_path
from .audit import _AUDIT_EDIT_TOOLS, _AUDIT_MSG_PREFIX, _audit_dispatch_role, _audit_hook_settings_path, _audit_lines, _audit_log_append
from .bridges import TOKEN_RULES, _bridge_fp, ask_bridge_text, confirm_bridge_text, vision_bridge_text
from .consts import _sessions, _sessions_lock
from ..eventlog import SessionEventLog, new_turn_id
from .meta import _meta, _meta_load, _meta_lock, _meta_save
from .models import available_models
from .prompts import _collect_system_prompt
from .transcript import re_title, _trace_append
from .vision import _cleanup_peer_reg, _model_vision_mode, _vision_load


# ---- from claude_harness.py:1036 (HarnessSession) ----


class HarnessSession:
    """一个 stream-json harness 会话（kind='harness'）。

    元数据（sid/title/model/cwd/session_id）持久化；进程是易耗品——
    闲置被回收、切回自动复活（--resume 续上下文）。port_id 稳定 =
    harness:<sid8>，前端 tab 与后端会话一一对应。
    """

    kind = "harness"

    def __init__(self, sid, cwd=None, model=None, session_id=None, title="", name=None,
                 permission=None, think=None, lineage=None):
        self.sid = sid
        self.port_id = "harness:" + sid[:8]
        self.cwd = cwd or os.path.expanduser("~")
        self.model = model or None
        self.session_id = session_id or None    # claude 侧真实会话 id（复活用）
        # v2.27.18 血统链（用户铁律：续命/重开可以，历史回放不能丢）：
        # 超窗续命等场景换过的新会话 session_id 依序记录。transcript_for
        # 按链把新旧 jsonl 串起来渲染——用户视角回放永远完整。
        self.lineage = list(lineage) if lineage else []
        self.title = title or ""
        self.name = name or None    # --name：peer 网络里别人按它寻址
        # v2.20：权限模式（auto=现状自动执行；confirm=写操作前 ask_user 确认）
        # 与思考等级（None=CLI 自主；low/medium/high/max → MAX_THINKING_TOKENS）。
        # 都随会话持久化，新会话 connect 时指定。
        self.permission = permission if permission in ("auto", "confirm") else "auto"
        self.think = think if think in ("low", "medium", "high", "max") else None
        self.hidden = False         # 识图后台会话：不进用户会话列表（不 sync_meta）
        self.is_vision = False      # 识图会话：start() 时用固定的基础提示词
        self.created = int(time.time() * 1000)
        self.last_active = self.created
        # ---- 运行时（进程相关，不持久化）----
        self._proc = None
        # v3.4.54：kill/revive 原子段锁（RLock——热更路径 kill_proc→revive_if_dead
        # 重入同锁）。规则：任何「查 alive → start()」序列必须持本锁，防并发
        # 复活双 Popen（threaded=True 下双 /send 同穿 alive=False 检查窗）
        self._start_lock = threading.RLock()
        # v3.4.54：busy/busy_since 迁移与泵事务锁（RLock——_run 重入
        # send_message 的 CAS 段、_turn_end 重入 _queue_pump 都靠重入）。
        # 全局锁序（防死锁单向序）：_sessions_lock > _start_lock >
        # _busy_lock > _meta_lock > _inbox_lock；_inbox_lock 是纯叶——
        # 锁内只允许纯内存操作，禁 emit/sync_meta/任何 IO
        self._busy_lock = threading.RLock()
        self._inbox_lock = threading.Lock()
        self.alive = False
        self.busy = False
        self.busy_since = None   # 本轮处理计时起点 ms（busy 时有效，供前端恢复计时）
        self.bridge_fp = None    # 注入时的识图引导词指纹（send 前热更检测，见 start()）
        self.renewed_at = 0      # v2.27.15：最近一次超窗续命的事件位点（HikLink 等待基准用）
        # v2.27.21：CLI 实报模型名（assistant 事件 message.model）。引导词/
        # 窗口判定以它为准——settings 默认名（如 glm-5.3-flash[1M]）与实跑名
        # （glm-5.3）会错位，三态分类按 settings 名算会把 MCP 类模型判成
        # inline/转交（用户实锤：切方案后仍转交识图会话，白等 7m44s）
        self.live_model = None
        # v2.27.20：peer 回传扫描态。_tr_sid 记路径归属的 session_id（续命/
        # resume 换代后旧路径作废重找）；_tr_lock 防 reader 线程与回传兜底
        # 轮询线程并发扫同一文件（偏移竞争会重复 emit peer 气泡）
        self._tr_sid = None
        self._tr_lock = threading.Lock()
        # v2.17 交互式提问：MCP 工具调用发起的待答问题
        #   {req_id, title, questions, answer, done, ts}
        self.ask = None
        self.ask_lock = threading.Lock()
        # v3.0 事件溯源：events/_seq/clients 三件套收编为 SessionEventLog
        #（信封注入/锁内 seq/epoch 断点续传/协议截断/投影归约，见
        #  src/eventlog/）。旧属性 _seq 保留为只读属性（to_meta/续命位点读）。
        self.log = SessionEventLog(self.sid)
        self._turn_id = None       # 当前回合 id（turn_* 事件与信封 turn 字段用）
        # v3.1（#10/#14）durable 输入账本：busy 期排队输入的服务端真源（此前
        # 纯前端本地队列，刷新即丢）。条目带世代 gen——/rewind 换代即作废旧
        # 代条目（回退后的世界线里它们失去意义）。随 meta 落盘跨重启/回收。
        self._inbox = []
        self._gen = 0
        self._pump_timer = None    # 回合终结自动泵的延迟器（防重入）
        self._closed = False       # v3.4.76R2：会话已删除——泵链/复活闸（R1）
        self._pumpFailN = 0        # v3.4.76R2：泵连续失败计数（R2 退避闸）
        # v2.34 light 审计记账（运行态，不持久化）：lines=本回合主会话
        # 单次直改（Edit/Write/MultiEdit/NotebookEdit）最大行数（v2.52 起
        # max 记账，回合累计口径废除）；files=空列表仅兼容保留（文件数
        # 口径已退役，不再记账）；designer/reviewer=本回合 Task 派发
        # 标记（SendMessage 续派也计入）——designer 旗是设计档豁免依据
        # （v2.54 设计线判定），reviewer 是唯一「审过」信号（结算追责与事中闸开闸
        # 都看它）；streak=连续违规回合数（防自动补审死循环：连续 3 回合
        # 违规后降级为仅警示）。回合结算（result/interrupted/exit）清零。
        # ids/pending 跨回合保留——agentId→角色映射（Task 结果回填）与
        # 在飞派发表，续派常发生在派发后的后续回合。
        self._audit = {"lines": 0, "files": [], "designer": False,
                       "designFired": False,   # v3.5.53：设计线事中一次性触发标志
                       "reviewer": False, "rev_at": 0,   # v3.5.100：审派发时的 lines 快照（再审判定=审后新增量）
                       "fired_at": 0,    # v3.5.100：上次审计触发时的 lines（防同水位重复触发）
                       "streak": 0, "ids": {}, "pending": {}}
        # v2.40：light 形态事中闸的 --settings 临时文件路径（kill 时清理；
        # revive 重启由 start() 重建——hooks 是进程启动参数，活进程不热更）
        self._audit_settings_path = None
        self.last_result = None
        # v3.5.98：会话创建时的 API 方案名（跨方案发消息拦截依据）。切方案
        # 会换网关/模型映射/上下文窗口，旧会话续发必然错位（上下文大小不一
        # 致/模型名不被新网关认）。None=升级前的旧会话（无标记），按用户拍板
        # 放行不拦；仅新会话起打标强制。
        self.scheme = None

    # ---- 元数据同步 ----
    @property
    def _seq(self):
        """只读兼容属性：事件序号真源在 log.store（分配在锁内）。"""
        return self.log.last_seq

    def to_meta(self):
        _inbox, _gen = self._inbox_snapshot()   # 单临界取二元组（快照与世代原子）
        return {"sid": self.sid, "title": self.title, "model": self.model,
                "cwd": self.cwd, "session_id": self.session_id,
                "lineage": self.lineage, "live_model": self.live_model,
                "name": self.name,
                "permission": self.permission, "think": self.think,
                "created": self.created, "last_active": self.last_active,
                # v2.35.2：事件序号随元数据落盘——会话对象被重建（闲置回收/
                # 重启后 _get_or_create）时续号。否则 _seq 归零重计，新事件
                # 序号全部小于前端快照里的旧 seq，被防重放守卫整批吞掉，
                # 会话看起来活着、事件永远不来（切不活跃会话场景的主害之一）
                "seq": self.log.last_seq,
                # v3.0：日志代际随元数据落盘——GC 重建沿用（可 resume），
                # /rewind 换代（客户端旧水位作废，只能 reset 重建）
                "epoch": self.log.epoch,
                # v3.1（#10/#14）：durable 输入账本 + 世代号——重启/闲置回收
                # 后队列不丢；gen 让 /rewind 后作废旧代条目的判定可跨重启
                "inbox": _inbox,
                "gen": _gen,
                # v3.5.98：会话方案名随元数据落盘（GC/重启后拦截判定不失忆）
                "scheme": self.scheme}

    def sync_meta(self):
        if getattr(self, "hidden", False):
            return          # 识图后台会话不出现在用户会话列表
        with _meta_lock:
            _meta_load()
            _meta[self.sid] = self.to_meta()
        _meta_save()

    # ---- 进程生命周期 ----
    def start(self):
        # 起进程前自愈：base_url 若指向自家代理但代理没在跑（上次强杀残留），
        # claude 读到死端口会全部请求失败——先恢复直连再 Popen（幂等，直连零开销）
        try:
            from src.proxy import ensure_direct_if_proxy_down
            ensure_direct_if_proxy_down("claude_start")
        except Exception:
            pass
        exe, is_shim = _resolve_claude_exe()
        argv = (["cmd.exe", "/c", exe] if is_shim else [exe])
        argv += ["-p",
                 "--input-format", "stream-json",
                 "--output-format", "stream-json",
                 "--verbose",
                 "--permission-mode", "auto"]
        # v2.17：注册交互式提问 MCP（ask_user）。--permission-mode auto 下任何
        # 未预授权的工具都会被权限系统拦下并自动拒绝（headless 没有提示通道），
        # 所以必须用 --allowedTools 预授权，否则 ask_user 调用直接失败。
        # --mcp-config 是追加式的（实测：内置 codegraph/headroom 等仍在），
        # 不会覆盖用户已有的 MCP。
        if not self.is_vision:
            # v3.5.36（用户拍板「多模态模型 MCP 直接不启用；非多模态默认启用」）：
            # vision server（本地兜底 analyze_image）按主会话模型形态注入——
            # inline（多模态直读）连 server 都不配，analyze_image 从工具列表
            # 彻底消失（模型连尝试入口都没有，比不预授权更干净）；非多模态
            # 默认注入（那是它唯一的看图通道）。ask_user 始终在（交互提问
            # 与识图无关）。
            _inline_mm = _model_vision_mode(self._eff_model()) == "inline"
            _cfg = _ask_mcp_cfg_path(self.sid, self.permission,
                                     include_vision=not _inline_mm)
            if _cfg:
                argv += ["--mcp-config", _cfg]
                # allowedTools 与 server 注入同步：vision server 没配时两个
                # 识图工具名也不预授权（网关主通道名同理——inline 时模型
                # 不该看到任何识图入口）
                _tools = ["mcp__harness__ask_user"]
                if _vision_load()["enabled"] and not _inline_mm:
                    # v3.5.104：本地工具升主通道，列前；网关 4_5v 降兜底列后
                    _tools += ["mcp__vision__analyze_image",
                               "mcp__4_5v_mcp__analyze_image"]
                argv += ["--allowedTools", ",".join(_tools)]
        # v2.14：识图后台会话用固定基础提示词；普通会话走用户提示词体系 +
        # 识图转交引导（主会话默认不知道有识图同伴，必须显式告知）。
        if self.is_vision:
            sys_prompt = (_vision_load().get("prompt") or "").strip()
            self.bridge_fp = None   # 识图会话自身不参与引导词热更
        else:
            # v2.20：model=None 的会话实际跑 settings 默认模型——多模态判定
            # 必须按实际模型来，否则默认多模态模型也被教去转交识图会话
            # v2.27.21：实报名（live_model）优先——revive 换词重启时按真实
            # 在跑模型注入（settings 名与实报名错位是转交 bug 的真根因）
            eff_model = self._eff_model()
            roles_txt = roles_bridge_text(eff_model)
            if roles_txt:
                # 角色定义随工具分发：起会话前按当前形态安装到
                # ~/.claude/agents/（幂等，light/heavy → designer+reviewer
                # 双装；mid → 只 reviewer 审计兜底；退役角色残留顺带清理）
                install_roles_agents(eff_model)
            parts = [_collect_system_prompt(self.cwd),
                     TOKEN_RULES,
                     roles_txt,
                     vision_bridge_text(eff_model),
                     ask_bridge_text()]
            if self.permission == "confirm":
                parts.append(confirm_bridge_text())
            sys_prompt = "\n\n".join(p for p in parts if p)
            # v2.27.13：记注入时的引导词指纹——系统提示是进程启动参数，
            # 活会话不会因代码升级/名单调整换新词（用户实锤：MCP 类模型
            # 揣着旧「转交版」绕识图会话白等 1m20s）。send 前对指纹热更。
            self.bridge_fp = _bridge_fp(eff_model)
            # v2.29~v2.49 的决策者结构禁权（--disallowedTools 全禁干活工具
            # 逼派发）已废——主会话=干活者要亲自干活，禁权失去意义
            # （roles_disallow/ROLE_DISALLOW 一并移除）。
            # light 形态事中闸：直改达轻审线上限且本回合尚未派过 reviewer
            # 时拦下一次并指路送审（审过即开闸——直干是常态，闸只逼送审
            # 不逼停工；见 harness_roles.audit_gate_check）。strong 不入闸
            # ——直改是设计常态，只有回合结算审计兜底（_audit_state 第三位
            # strong 旗分流）。闸与结算同源判定（audit_mode=off 时闸与审计
            # 同步关）；注入失败照常启动（闸失效不阻塞工作）。
            # v3.5.51（用户拍板「至少等改完才咬」）：事中闸退役——不再注入
            # PreToolUse hook（中途拦直改会把大改切成两半）。审计统一回合结束
            # 结算追责（_audit_settle 按线咬：补审/补方案指令自动续发），派发
            # 标记（designer/reviewer）结算时照样核验——追责能力不降，只去掉
            # 中途打断。_audit_settings_path 随之不再生成。
        if sys_prompt:
            argv += ["--append-system-prompt", sys_prompt]
        if self.name:
            argv += ["--name", self.name]     # peer 寻址名（识图会话靠它被找到）
        # 复活：claude 侧已有真实 session_id → --resume 续上下文
        if self.session_id:
            argv += ["--resume", self.session_id]
        if self.model:
            argv += ["--model", self.model]
        env = dict(os.environ)
        env.setdefault("TERM", "dumb")
        # v2.20：思考等级 → CLI 的 MAX_THINKING_TOKENS（透传到网关/模型侧
        # 的 thinking budget；不支持时被忽略，无害）
        if self.think:
            env["MAX_THINKING_TOKENS"] = str(
                {"low": 4096, "medium": 10240, "high": 20480, "max": 31999}[self.think])
        _trust_workspace(self.cwd)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            argv, cwd=self.cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags)
        self.alive = True
        self.busy = False
        # v2.35：本进程实例已见的 init 事件数——第 2 个起是「新回合起跑」
        # （CLI 自发回合：后台任务完成通知/协作回传续跑），据此补置 busy
        self._init_n = 0
        self.last_active = int(time.time() * 1000)
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _audit_settings_cleanup(self):
        """v2.40：删事中闸 --settings 临时文件并清引用（claude 启动时已读
        完；revive 重启会重建新文件）。kill_proc 与 reader loop 自然死亡
        路径（finally 不走 kill_proc）都要调——漏后者的话 revive 的 start()
        覆盖 _audit_settings_path，旧文件每次死亡-复活泄漏一个到 %TEMP%。"""
        _p = getattr(self, "_audit_settings_path", None)
        if _p:
            self._audit_settings_path = None
            try:
                os.remove(_p)
            except Exception:
                pass

    def kill_proc(self, quiet=False):
        """只杀进程保元数据与事件缓冲（闲置回收/复活前清理用）。
        v2.14：强杀会让 claude 来不及清理 peer 注册条目（~/.claude/sessions/
        <pid>.json），残留条目指向死 pid —— 下次 ListAgents 会看到幽灵会话。
        所以杀完主动清理自己那条注册。
        v2.20：quiet=True 吞掉随之而来的 exit 事件——会话内切模型重启进程
        是计划内动作，不该弹「会话进程已结束」吓人。
        v2.25：进程已死透（reader loop 早已收尾）时不设 _suppress_exit——
        标志位无人消费会残留，吞掉下一次真正的意外退出（两次切模型且
        中间进程已自然退出的触发链）。
        v3.4.54：整体持 _start_lock——kill 是 revive 的前置清理，两段各自
        持锁会在间隙漏进并发 start（proc.kill/wait ≤2s 有界 IO，可入锁）。"""
        with self._start_lock:
            self.alive = False
            with self._busy_lock:      # 锁序 _start_lock > _busy_lock（单向）
                self.busy = False
            self._audit_settings_cleanup()
            if quiet:
                proc_alive = bool(self._proc and self._proc.poll() is None)
                if proc_alive:
                    self._suppress_exit = True
            self.ask_cancel()       # v2.17：别让 MCP 侧的提问继续空转等
            proc, self._proc = self._proc, None
            if proc is not None:
                pid = None
                try:
                    pid = proc.pid
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
                if pid or self.session_id:
                    _cleanup_peer_reg(pid, self.session_id)

    def close(self):
        # v3.4.76R（复核问题四）：先取消泵重试链——close 后 3s 链到点会把
        # 已删会话的 inbox 回插+sync_meta 复活进账本（窗口 0.8s→3.8s 被重试
        # 机制放大）。cancel 后链即断，_run 到点也见 timer 被换不复活
        try:
            with self._inbox_lock:
                self._closed = True   # in-flight _run 的 revive/挂链闸（R1）
                if self._pump_timer:
                    self._pump_timer.cancel()
                    self._pump_timer = None
        except Exception:
            pass
        self.kill_proc()
        try:
            if getattr(self, "reader", None) and self.reader.is_alive():
                self.reader.join(timeout=1.0)
        except Exception:
            pass

    def revive_if_dead(self):
        """已死会话复活（有 claude session_id 才能续上下文）。返回能否用。
        v3.4.54：整体持 _start_lock 且锁内复查 alive（双检）——与 kill_proc
        同锁原子，并发复活只允许一个 start() 胜出。"""
        with self._start_lock:
            if self.alive:
                return True
            if not self.session_id:
                return False
            try:
                self.start()
                return True
            except Exception:
                return False

    # ---- 输入 ----
    def _is_remote_bot_session(self):
        """本会话是否 HikLink 小助手专属会话（远程通道，无人在场）。
        判定：hiklink 单例记着的 harness sid 就是本会话（controller 在但
        sid 对不上=GUI 会话，不能静默换会话）。"""
        try:
            from src import hiklink_bot as hb
            ctl = hb._controller
            return bool(ctl and ctl._sid and ctl._sid == self.sid)
        except Exception:
            return False

    def _eff_model(self):
        """v2.27.21：有效模型名——CLI 实报（live_model）优先于会话 model
        优先于 settings 默认。识图三态/上下文窗口判定统一走这里：实报名
        才是真正在跑的模型（settings 名经网关映射后可能完全不同，实测
        flash 名义 inline vs 实跑 glm-5.3 应为 mcp，错位导致错误引导词）。"""
        return self.live_model or self.model or available_models().get("default")

    # ---- light 形态回合结算审计（strong 形态也结算）----
    def _audit_tally(self, o):
        """回合内审计记账：只记主会话调用——子代理事件带 parent_tool_use_id
        一律不算（它们有自己的纪律，主会话的违规才算违规）。纯计数不读
        配置（每事件零盘 IO），判不判定是 _audit_settle 结算时的事。
        v2.52 用户拍板：lines 记**单次直改的最大行数**（原为回合累计——
        累计口径废除，切片拆小不追责，只有一次性改超才审计）；files 列表
        不再有判定消费方，不再记账（键保留兼容旧结构）。SendMessage 续派
        口径——主会话经 SendMessage 续派 designer/reviewer 也计派发标记
        （经 _audit_dispatch_role 按 input.to 识别），并在 Task/Agent 派发
        时记 pending（等 result 回填 agentId→角色映射）。"""
        au = self._audit
        if o.get("parent_tool_use_id"):
            return
        blocks = (o.get("message") or {}).get("content")
        if not isinstance(blocks, list):
            return
        for b in blocks:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            n = str(b.get("name") or "")
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            if n in _AUDIT_EDIT_TOOLS:
                # v3.5.41（用户实锤「审计线没生效」严查）：口径从「单次最大」
                # 改「回合累计」——旧口径下 AI 把大改拆成多次小 Edit（每次
                # <免审线）即永久免审（真实转写复算：回合总和 174 行、单次
                # max 25，零审计）。切片拆小不追责的旧定调随本次口径作废
                au["lines"] = (au.get("lines") or 0) + _audit_lines(n, inp)
                continue
            role = _audit_dispatch_role(n, inp, au.get("ids") or {})
            if not role:
                continue
            au[role] = True
            tu_id = str(b.get("id") or "")
            if n in ("Task", "Agent") and tu_id:
                # 记在飞派发：result 到达时回填 agentId→role（SendMessage 用
                # 裸 agentId 寻址的续派可判角色，见 _audit_tally_result）
                au.setdefault("pending", {})[tu_id] = role

    def _audit_tally_result(self, o):
        """v2.50（P1）：user 事件侧的审计累计——Task/Agent 派发的 result
        到达时回填 agentId→角色映射（续派 SendMessage 用裸 agentId 寻址时，
        _audit_dispatch_role 查本映射判角色）。agentId 提取复用 v2.46R 的
        宽容正则（JSON \"agentId\":\"x\" 与裸文本 agentId: x 两形态）。
        失败静默——映射缺了只是那类续派计不上派发标记（保守漏计），
        不致命。"""
        if o.get("parent_tool_use_id"):
            return
        au = self._audit
        pend = au.get("pending") or {}
        if not pend:
            return
        blocks = (o.get("message") or {}).get("content")
        if not isinstance(blocks, list):
            return
        for b in blocks:
            if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                continue
            role = pend.pop(str(b.get("tool_use_id") or ""), None)
            if role is None:
                continue
            txt = b.get("content")
            if isinstance(txt, list):
                txt = " ".join(str(x.get("text") or "") for x in txt
                               if isinstance(x, dict))
            m = re.search(
                r"(?<![a-zA-Z])agentId[\"\':\s]+([0-9a-zA-Z_-]{8,64})",
                str(txt or ""))
            if m:
                ids = au.setdefault("ids", {})
                ids[m.group(1)] = role
                if len(ids) > 256:   # 防无界增长：淘汰最旧（续派大概率用最近的）
                    ids.pop(next(iter(ids)))

    def _audit_state(self):
        """审计现值：(audit_mode, (l1, l2f, l2l) 两档线, strong)；不审计
        返回 None。条件=roles 开 + audit_mode != off + 形态非重档（v3.5.0：
        heavy 最信任档 _audit_state 直接 None——事中闸/回合结算/补审全免）。
        light/mid 都结算审计（违规判定走 audit_verdict 的对应分支），
        strong 旗仅供调用方分流（verdict 分支与闸的 hook 注入，v3.5.0 起
        =形态是 mid）；事中闸（/audit_gate 与 start 的 hook 注入）仅
        light——mid 直改是设计常态，且两形态违规补救统一为派 reviewer
        补审（reviewer 两形态都装）。结算时读一次盘——配置改动回合间生效。
        线值统一出自 harness_roles.audit_limits（与引导词同源，词里一套
        数字审计另一套是 v2.34 就防的坑）。"""
        try:
            from .roles import roles_cfg, roles_mode, audit_limits
            cfg = roles_cfg()
            mode = str(cfg.get("audit_mode") or "auto")
            if not cfg.get("enabled") or mode == "off":
                return None
            _m = roles_mode(self._eff_model())
            if _m == "heavy":
                return None
            strong = (_m == "mid")
            return mode, audit_limits(cfg), strong
        except Exception:
            return None

    def _audit_settle(self, reason):
        """回合结算审计（result/interrupted/exit 三处调用）。违规判定走
        harness_roles.audit_verdict（纯函数，与引导词两档线同源）：
        ① light：单次直改超免审线未派 reviewer 轻审——中改档违规；
        单次超轻审线属大改须取证级全审却未派审——大改档违规；② strong：
        单次超审计线未派 reviewer 审计——违规。判定只看单次直改总行数
        （v2.52 用户拍板：不计文件数、不做回合累计，切片拆小不追责）。
        designer 派发豁免设计档（v2.54 设计线；设计不产生直改、不算已审）。
        两形态补救统一
        为派 reviewer 补审（不再分形态——reviewer 两形态都装）。
        兜底按 audit_mode：auto=回合结束自动续发一条 [审计] user 消息
        （复用 send_message 管线，busy/进程/指纹热更检查全继承）；warn=
        仅聊天流红色警示（前端 kind='audit' 事件）——提示性兜底，不阻断。
        防循环：连续 3 个违规回合后降级仅警示；中断/进程退出只警示不续发
        （用户主动停/进程已死，续发无意义，且不计入 streak）。计数结算后
        清零。"""
        au = self._audit
        lines = au["lines"]
        designed = au.get("designer")
        # v3.5.100（用户拍板「回合以我的消息为界」）：**结算不再清任何累计**
        # ——lines 跨 AI 回合累计到下一条用户消息（中间多少次 result/子代理
        # 都算同一大回合）；designer 旗同（大回合内出过设计即算，v3.5.99）；
        # reviewer 派发记 rev_at 快照——「审后再改再审」按审后新增量判定
        st = self._audit_state()
        if st is None:
            au["streak"] = 0
            return
        mode, limits, strong = st
        l1, _l2f, l2l = limits
        line_need = l2l if strong else l1          # 需审线（light=免审线上沿 / strong=审计线）
        reviewed = au.get("reviewer")
        unaudited = lines - (au.get("rev_at") or 0)   # 审后未审的改动量（未审过=全部）
        fired = au.get("fired_at") or 0
        viol = []
        if lines > line_need and unaudited > line_need and lines > fired:
            if strong:
                viol.append("主会话直改累计 %d 行，超过审计线（≤%d 行），其中 %d 行尚未派 reviewer 审计"
                            % (lines, l2l, unaudited))
            elif lines <= l2l:
                viol.append("主会话直改累计 %d 行，超过免审线（≤%d 行）属中改，其中 %d 行尚未派 reviewer 轻审（只审 diff）"
                            % (lines, l1, unaudited))
            else:
                viol.append("主会话直改累计 %d 行，超过轻审线（≤%d 行）属大改，其中 %d 行尚未派 reviewer 取证级全审"
                            % (lines, l2l, unaudited))
        dl = design_limit(cfg=None)
        if dl > 0 and not designed and lines >= dl and lines > fired:
            viol.append("主会话直改累计 %d 行，达到设计线（≥%d 行）属大改，尚未先派 designer 出框架方案——大改须方案先行"
                        % (lines, dl))
        if not viol:
            if reviewed:
                au["streak"] = 0
            return
        desc = "；".join(viol)
        au["fired_at"] = lines   # v3.5.100：触发水位记账（同水位不重复触发；审后新增量再触发）
        if reason == "result":
            au["streak"] += 1
        degraded = au["streak"] >= 3
        if reason == "result" and mode == "auto" and not degraded:
            # 自动补审：卡文本与续发消息同一字符串（v2.34.1 统一——实时/
            # 落盘回放/模型所见三处一致）。续发走后台线程，send_message 与
            # 用户抢发竞争时返回失败——静默记 log，卡已到位，不重试。
            # v2.52：文案去「Task 工具」——工具名随 CLI 版本变（Task→Agent），
            # 只说派 reviewer，派发方式模型自己知道。
            # v2.54：违规含设计档时续发要求先补方案（派 designer）再实施。
            remedy = ("已自动续发补正指令——先派 designer 代理出框架方案"
                      "（带上全部已知上下文），按方案继续实施；未审的改动"
                      "立即派 reviewer 代理补审（对抗审核：只审不改，给 "
                      "PASS/FAIL 结论）" if "designer" in desc else
                      "已自动续发补审指令——立即派 reviewer 代理补审上述"
                      "改动（对抗审核：只审不改，给 PASS/FAIL 结论）")
            text = (_AUDIT_MSG_PREFIX + "%s。" % desc + remedy +
                    "按结论处理：FAIL 自己修复后复审，PASS 才算完成，然后"
                    "再答复用户。不要辩解，直接补正。")
            self._audit_card(text)
            threading.Thread(target=self._audit_send, args=(text,),
                             daemon=True).start()
            return
        why = {"interrupted": "（回合被中断，仅记录不自动续发）",
               "exit": "（会话进程已退出，仅记录不自动续发）"}.get(reason, "")
        tail = ("已连续 %d 个回合违规，自动续发已降级为仅警示（防循环烧 "
                "token），请人工介入。" % au["streak"]) if degraded else \
               ("审计模式为 %s，仅警示不自动续发——请手动派 reviewer 补审。"
                % mode)
        self._audit_card(_AUDIT_MSG_PREFIX + "%s。%s%s" % (desc, tail, why))

    def _audit_card(self, text):
        """审计警示卡：emit（实时 SSE 红卡）+ 落盘 audit log（回放持久）。
        v2.34.1 前只 emit——warn/降级/中断档的卡不落转写，刷新/切会话即失。"""
        self.emit({"kind": "audit", "text": text[:4000]})
        _audit_log_append(self.sid, text)

    def _audit_send(self, text):
        """审计自动续发：补审指令作为 user 消息发回本会话（模型视角=用户
        要求补审），走正常 send_message 管线。text 以 _AUDIT_MSG_PREFIX
        开头 → send_message 里不画用户气泡（警示事件已由 _audit_settle 先行
        emit）。失败静默（log）——用户抢先发消息/进程退出属正常竞争，不重试
        不阻塞。"""
        try:
            ok, err = self.send_message(text, boundary=False)
            if not ok:
                log.warning("[审计] 补审续发未发出：%s", err)
        except Exception as e:
            log.warning("[审计] 补审续发异常：%s", e)

    def _autorenew_on_overflow(self, text, image_paths, file_paths,
                               used, mwin, eff_model):
        """超窗自动续命（v2.27.15，仅小助手这类远程无人在场会话）。
        旧会话上下文已超当前模型窗口（切 API 方案模型变小所致）——拒发的话
        手机侧永远收不到回复。做法：导出旧对话主干注入新会话首条消息，
        self 改指新 claude session_id（对外 sid 不变，用户无感），
        再把本条消息作为正常轮次发出。返回 True=已续命并已发送。
        失败路径返回 False 走原有拒发提示（别把用户消息吞了）。"""
        if getattr(self, "is_vision", False):
            return False   # 识图配角会话不续命
        try:
            from src.claude_sessions import export_session_transcript
            lines, _cwd = export_session_transcript(self.session_id)
        except Exception:
            return False
        if not lines:
            return False   # 导不出历史（文件没了/空）→ 没有可迁移的东西
        # 历史注入首条消息：远超窗口的完整历史没法塞，按轮次收尾的对话主干
        # 足够新会话延续任务记忆。角色对齐精简格式，长块截断防超窗复发。
        parts = []
        for ln in lines:
            role = {"user": "用户", "assistant": "助手",
                    "tool": "（工具）", "system": "（摘要）"}.get(ln.get("role"), "（其他）")
            parts.append("%s：%s" % (role, (ln.get("text") or "").strip()))
        hist = "\n".join(parts)
        # 旧历史压缩到新窗口的 ~60%（给回复/工具留余量），超长从头截断保最近
        budget = int(mwin * 0.6)
        if len(hist) > budget:
            hist = "……（更早历史已截断）\n" + hist[-budget:]
        old_title = self.title
        # 换新 claude 会话：杀旧进程（元数据保留）、清 session_id 全新 start。
        # 不能走 revive_if_dead——它要求 session_id 非空（--resume 语义），
        # 这里恰恰是开新会话，必须裸 start。
        # v2.27.18：旧 session_id 记入血统链——transcript_for 按链串接历代
        # jsonl，历史回放不丢（用户铁律：重开可以，回放不能丢）。
        # v3.4.54R（全审回炉）：kill+换代+start 整体持 _start_lock——对象已
        # 发布进 _sessions，锁外间隙并发 revive_if_dead 会双 Popen
        with self._start_lock:
            self.kill_proc(quiet=True)
            if self.session_id:
                self.lineage = list(getattr(self, "lineage", None) or []) + [self.session_id]
            self.session_id = None
            self.title = None           # 让首条真实消息重新定标题
            try:
                self.start()
            except Exception as e:
                log.warning("超窗续命：新会话启动失败 %s", e)
                return False
        seed = ("[系统] 上一会话上下文已超当前模型窗口，自动重开。以下是此前"
                "对话历史记录，请据此延续原有任务脉络：\n\n%s\n\n[系统] 历史结束。"
                % hist)
        ok, err = HarnessSession.send_message(self, seed, boundary=False)
        if not ok:
            log.warning("超窗续命：历史注入失败 %s", err)
            return False
        # 等注入轮完成再发用户本条（不并发写 stdin）
        deadline = time.time() + 600
        while time.time() < deadline and self.busy:
            time.sleep(1)
        if self.busy:
            return False   # 注入轮 10 分钟没跑完，放弃（消息原样走拒发）
        self.title = old_title or self.title
        self.sync_meta()
        # 续命位点：调用方（HikLink _run_cmd）据此把等待基准挪到用户本条
        # turn——注入轮的 result 不算数，否则推空「没有文本回复」
        self.renewed_at = self._seq
        ok, err = HarnessSession.send_message(self, text or "", image_paths, file_paths)
        if not ok:
            log.warning("超窗续命：重发用户消息失败 %s", err)
            return False   # 用户消息没发出去 → 走拒发提示，别静默吞
        return True

    def send_message(self, text, image_paths=None, file_paths=None, boundary=True):
        """发消息：文本 + 可选图片（base64 块，实测网关透传）+ 文件路径（文本
        附录，任何模型都能用 Read 读）。返回 (ok, err)。"""
        # 上下文超窗拒发（用户定调）：切 API 方案会把模型强制跟着切小窗
        # （快照带模型映射），1M 会话攒超 256K 后发消息必 400 prompt is
        # too long（实测 267112 > 262144）——直接拦在发送前并给出路。
        # 3% 余量：prompt 除历史外还有 system/工具定义等固定开销。
        # /compact 后 _session_ctx_used 撞压缩边界归零，即可继续发。
        # v3.5.98：跨方案拒发（用户需求「切了方案就不让发，新开会话」）——
        # 会话创建时打的方案名与当前激活方案不一致 → 拒发。不同方案的
        # 模型映射/上下文窗口完全不同，旧会话续发必错位。仅拦有标记且
        # 不一致的（用户拍板：无标记的升级前旧会话放行）。
        try:
            from src.claude_default import active_scheme_name
            cur_scheme = active_scheme_name()
            if self.scheme and cur_scheme and self.scheme != cur_scheme:
                return False, ("当前 API 方案是「%s」，本会话是「%s」方案创建的——"
                               "模型映射与上下文窗口已随方案切换，旧会话续发会错位。"
                               "请新建会话（历史消息仍可在列表中回看）"
                               % (cur_scheme, self.scheme))
        except Exception:
            pass
        try:
            eff_model = self._eff_model()
            if eff_model and self.session_id:
                used, _w, _c = _session_ctx_used(self)
                # v2.27.22：窗口走候选链（配置名后缀优先）——实报裸名无 [1M]
                # 信息，单看它 1M 会话会被判成 256K 误拒（用户实锤）
                mwin = _session_ctx_window(self)
                if used and used >= int(mwin * 0.97):
                    # v2.27.15：小助手自动续命（用户定调：超窗时自动重开会话
                    # 并映射旧链接，手机侧无感）。500K 历史塞不进 256K 窗口，
                    # headless 也无手动 /compact 入口——唯一出路是开新会话：
                    # 导出旧对话主干 → 首条消息注入历史 → 改 session_id 映射，
                    # 用户视角「还是那个小助手」。只有远程通道（HikLink 小
                    # 助手）无人在场才自动续命——GUI 会话有人看着提示即可，
                    # 静默换会话违背「我不同意方案A」的定调。
                    if self._is_remote_bot_session() and \
                            self._autorenew_on_overflow(text, image_paths, file_paths,
                                                        used, mwin, eff_model):
                        return True, None
                    # v2.28.10：/compact 是超窗的解药，守卫必须放行——否则满窗
                    # 时唯一出口被自己锁死（用户实锤：手动压缩发不出去，红条
                    # 就是拒发语）。压缩后 _session_ctx_used 撞压缩边界归零。
                    # v2.28.11：爆死态（单轮巨量注入，如 Read 大图）连 /compact
                    # 都压不动（压缩请求自身超窗）——/rewind 回退是终极逃生门。
                    if not (text or "").lstrip().startswith("/compact"):
                        return False, ("当前上下文已约 %dK tokens，超过模型「%s」"
                                       "的 %dK 窗口——可 /rewind 回退上一回合"
                                       "（强烈推荐，立即恢复），或 /compact 压缩"
                                       "（爆死态可能压不动），或新建会话"
                                       % (round(used / 1024),
                                          eff_model,
                                          round(mwin / 1024)))
        except Exception:
            pass   # 检测自身失败不拦发送（读不到用量时维持原行为）
        # v3.5.100（用户拍板「回合以我的消息为界」）：用户消息=大回合边界——
        # 审计累计全线清零（lines/审派发/designer/streak），下一条消息起重新
        # 计账。boundary=False（审计续发等系统消息）不清——补审指令不是用户
        # 边界，不清会把手头的审计状态抹掉
        if boundary:
            try:
                self._audit.update({"lines": 0, "files": [], "designer": False,
                                    "designFired": False, "reviewer": False,
                                    "rev_at": 0, "fired_at": 0, "streak": 0})
            except Exception:
                pass
        # base_url 死代理自愈的第二时机（用户实锤）：start 里的自愈只在起
        # 进程时跑——claude 启动时代理还活着、之后代理被停，进程不死就永远
        # 不走 start，消息全打进死端口。发送前发现 base_url 已恢复直连，
        # 就重启进程换新配置（有 session_id 则复活续上下文，本条照常发）。
        if self.alive and not self.busy:
            try:
                from src.proxy import ensure_direct_if_proxy_down
                if ensure_direct_if_proxy_down("claude_send"):
                    with self._start_lock:      # kill+revive 原子对（重入子调用同锁）
                        self.kill_proc(quiet=True)
                        if not self.revive_if_dead():
                            return False, "会话进程已退出（base_url 已恢复直连，请重发）"
            except Exception:
                pass
            # v2.27.13：识图引导词过期热更——系统提示是进程启动参数，代码升级
            # / mm_mcp 名单调整后活会话仍揣旧词（用户实锤：MCP 类模型被旧
            # 「转交版」带去绕识图会话白等）。指纹变了就 kill+resume 静默换新
            # （与切模型同款，上下文保留），本条消息照常发。
            if self.alive and self.bridge_fp is not None:
                try:
                    eff_model = self._eff_model()
                    if _bridge_fp(eff_model) != self.bridge_fp:
                        with self._start_lock:  # kill+revive 原子对（重入子调用同锁）
                            self.kill_proc(quiet=True)
                            if not self.revive_if_dead():
                                return False, "会话进程已退出（识图引导词已更新，请重发）"
                except Exception:
                    pass
            # v2.37（P0+）派发前自愈：Task/SendMessage 派发前确保本形态角色
            # 定义在位（幂等重装，几毫秒）——兜住一切上游删除路径（旧版互清/
            # 测试误清/人工误删）。发生过缺失自愈时红卡告警：此前派发可能
            # 已回落主链轻模型，用户须知情。仅角色开关启用时介入。
            try:
                from .roles import ensure_roles_ready
                _miss = ensure_roles_ready(self._eff_model())
                if _miss:
                    self.emit({"kind": "audit",
                               "text": "检测到角色定义缺失（%s）已自动恢复——"
                                       "此前派发可能回落主链模型，建议重发该任务"
                                       % "、".join(m[:-3] for m in _miss)})
            except Exception:
                pass
        if not self._proc or not self.alive:
            return False, "会话进程已退出"
        # v3.4.54：CAS+stdin 写+回合起跑整体入 _busy_lock——此前检查与置位
        # 之间仍可换线程（两条 NDJSON 交叠写管道）。busy_since 随置位（被拒
        # 的并发 send 不再重置在飞回合的前端计时基准）。贴图 base64 读盘
        # 可能慢，正是要的串行化语义（per-session 锁，跨会话零影响）。
        # 注：泵 _run 曾持本锁重入此处（v3.4.54R 泵改造移除该路径——防
        # AB-BA 死锁）；RLock 保守保留
        with self._busy_lock:
            if self.busy:
                return False, "claude 正在回复中，请稍候"
            self.busy = True
            self.busy_since = int(time.time() * 1000)   # 处理计时起点（前端切会话回来显示真实已跑时长）
            content = []
            for p in (image_paths or []):
                try:
                    with open(p, "rb") as f:
                        data = base64.b64encode(f.read()).decode()
                    ext = os.path.splitext(p)[1].lower().lstrip(".") or "png"
                    media = "image/" + ("jpeg" if ext in ("jpg", "jpeg") else ext)
                    content.append({"type": "image",
                                    "source": {"type": "base64", "media_type": media, "data": data}})
                except Exception:
                    continue
            full_text = text or ""
            att = list(image_paths or []) + list(file_paths or [])
            if att:
                att_lines = "\n".join(att)
                full_text = (full_text + "\n\n" if full_text else "") + \
                    "[附件，可用 Read 工具读取]\n" + att_lines
            if not full_text and not content:
                self.busy = False
                return False, "消息为空"
            if not full_text and content:
                full_text = "请查看图片"
            if content:
                content.append({"type": "text", "text": full_text})
            else:
                content = full_text
            try:
                payload = {"type": "user", "message": {"role": "user", "content": content}}
                self._proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                self._proc.stdin.flush()
            except Exception as e:
                self.busy = False
                return False, "发送失败：%s" % e
            self.last_active = int(time.time() * 1000)
            # v3.0：stdin 写成功即回合起跑（turn_started 先于 user_echo/renew，
            # 信封 turn 字段从本回合第一条事件起生效）
            self._turn_start()
            # v2.34.2（R1）：判定收窄到 _AUDIT_MSG_PREFIX（_audit_settle 续发
            # 消息的唯一句式开头）——不定标题、不画用户气泡（警示已由
            # _audit_settle 的 kind='audit' 事件先行呈现）。用户手打「[审计]…」
            # 开头的普通消息不命中，照常走 user_echo 画气泡。
            _audit_msg = (text or "").lstrip().startswith(_AUDIT_MSG_PREFIX)
            # 首条消息定标题（微信式：会话标题=首句）
            if not self.title and text and not _audit_msg:
                self.title = re_title(text)
                self.sync_meta()
            # v2.27.23：超窗续命的 [系统] 历史注入不推原文——几十万 token 刷满
            # 消息流（用户定调"后台化"）。改推 renew 分割线事件，前端一行带过。
            if _audit_msg:
                pass
            elif (text or "").lstrip().startswith("[系统] 上一会话上下文已超当前模型窗口"):
                rounds = sum(1 for _ln in text.splitlines()
                             if _ln.startswith(("用户：", "助手：")))
                self.emit({"kind": "renew",
                           "text": "上下文超窗，已自动重开会话（%d 轮历史已后台迁移）" % rounds})
            else:
                self.emit({"kind": "user_echo", "text": text or "",
                           "images": list(image_paths or []), "files": list(file_paths or [])})
            return True, None

    def interrupt(self):
        """中断当前回复：kill 进程（claude 中断语义无 stdin 通道，杀进程即停），
        事件缓冲保留，下次发送自动复活续上下文。"""
        if not self.alive or not self.busy:
            return False, "当前没有进行中的回复"
        threading.Thread(target=self._interrupt_async, daemon=True).start()
        return True, None

    def _interrupt_async(self):
        # v2.25：去掉 stdin 空写探活——0 字节写对部分 CLI 会被当作 EOF/空行
        # 事件（审计 §三.10），且探活结果无人消费，紧随的 kill 已覆盖停机语义
        self.kill_proc()
        # v2.34：中断也结算审计——直改半截/审核跳过同样算违规记录（仅警示
        # 不续发：用户主动停，续发违背意图）。须在 emit interrupted 前调，
        # 警示先于「已中断」行出现。
        try:
            self._audit_settle("interrupted")
        except Exception:
            pass
        self.emit({"kind": "interrupted", "text": "已中断回复"})
        _trace_append(self.sid, "interrupted", "已中断回复")   # v3.4.87：痕迹持久化（重启后回放可见）
        self._turn_end(err=True)

    # ---- durable 输入账本（#10/#14，v3.1）----
    def queue_admit(self, text, image_paths=None, file_paths=None, eid=None):
        """busy 期输入入队（服务端真源）。事件流同步 input_admitted，前端
        队列 UI 与本地状态由事件驱动——连接在别的设备也能看到同一条队列。
        eid：客户端预生成 id（POST 与 SSE 事件赛跑的防双画锚点），合法即
        采用；缺省/非法由服务端发号。"""
        import uuid as _uuid
        if not (isinstance(eid, str) and 6 <= len(eid) <= 32
                and all(c in "0123456789abcdefghijklmnopqrstuvwxyz"
                        for c in eid.lower())):
            eid = _uuid.uuid4().hex[:12]
        with self._inbox_lock:         # 纯叶锁：只改内存，emit/sync_meta 在锁外。
            # v3.4.54R：gen 读取随 append 同临界——锁外构造时 bump 插中间
            # 会让条目挂旧代成永不泵发的僵尸
            entry = {"id": eid,
                     "text": text or "",
                     "images": [str(p) for p in (image_paths or [])],
                     "files": [str(p) for p in (file_paths or [])],
                     "gen": self._gen, "ts": int(time.time() * 1000)}
            self._inbox.append(entry)
        self.emit({"kind": "input_admitted", "id": entry["id"],
                   "text": (text or "")[:200], "gen": self._gen,
                   "att": len(entry["images"]) + len(entry["files"])})
        self.sync_meta()
        return entry["id"]

    def queue_list(self):
        with self._inbox_lock:
            return [dict(e) for e in self._inbox]

    def _inbox_snapshot(self):
        """to_meta 用的队列快照（v3.4.54：to_meta 在 _meta_lock 下嵌套取
        _inbox_lock——锁序 _meta_lock > _inbox_lock 单向，合法短临界）。
        v3.4.54R：快照与 gen 合一单临界——两段锁间穿插 bump 会落盘
        {gen: N+1, inbox: [旧代条目]}，重启恢复出永不泵发的僵尸条目。"""
        with self._inbox_lock:
            return [dict(e) for e in self._inbox], self._gen

    def queue_discard(self, eid, reason="user"):
        found = False
        with self._inbox_lock:
            for i, e in enumerate(self._inbox):
                if e.get("id") == eid:
                    self._inbox.pop(i)
                    found = True
                    break
        if found:
            self.emit({"kind": "input_discarded", "id": eid,
                       "reason": reason})
            self.sync_meta()
        return found

    # v3.5.109（designer F3）：泵延迟可注入——测试覆写实例属性即可秒级驱动
    # 泵链路，根治「sleep 1.6s 等 800ms 泵」的时序 flaky 类（test_ledger 实锤）
    _PUMP_DELAY = 0.8     # 回合终结 → 泵发首条的留窗（result 收尾/用户中断）
    _PUMP_RETRY = 3.0     # busy 期/瞬态失败的泵重试周期

    def queue_to_head(self, eid):
        """「立即发送」：条目提到队首，随后中断当前回合 → 回合终结泵自然
        先发它。条目不存在返回 False（已在队首也算存在，返回 True）。"""
        found = moved = False
        with self._inbox_lock:
            for i, e in enumerate(self._inbox):
                if e.get("id") == eid:
                    found = True
                    if i:
                        self._inbox.insert(0, self._inbox.pop(i))
                        moved = True
                    break
        # v3.5.106：提队首也是顺序变更，落 meta（锁外——既有锁序 meta→inbox，
        # 锁内反取会构成 inbox→meta 的 AB-BA 死锁风险）；已在队首不动不落
        # v3.5.108（轻审低3）：_closed 守卫——不复活刚删会话
        if moved and not self._closed:
            self.sync_meta()
        return found

    def queue_order(self, ids):
        """拖拽排序：按 ids 重排账本（v3.5.109 自 routes 内联下沉——designer
        F2，归位 session 层、解锁测试直连；路由只剩薄调用）。重复 id 首现
        生效（v3.5.108）；未列出的条目按原相对序追加尾部不丢；落账后
        sync_meta（v3.5.106，_closed 守卫随行）。返回落账后的权威 id 序
        ——前端按它重建本地缓存，写响应即对账（designer 方案 D，收窄
        「order 在途被回合终结对账弹回旧序」的视觉窗口）。"""
        seen = set()
        ordered = []
        for i in (ids or []):
            i = str(i or "").strip()
            if i and i not in seen:
                seen.add(i)
                ordered.append(i)
        with self._inbox_lock:
            by = {e.get("id"): e for e in self._inbox}
            new_order = [by[i] for i in ordered if i in by]
            new_order += [e for e in self._inbox if e.get("id") not in seen]
            self._inbox = new_order
            out = [e.get("id") for e in new_order]
        if not self._closed:   # 锁外（锁序 meta→inbox）；不复活刚删会话
            self.sync_meta()
        return out

    def bump_generation(self, reason="rewind"):
        """#14 分支世代：/rewind 后调用。旧代排队输入全部作废（事件显式通
        知，前端队列同步清空），世代号自增——此后入队条目都挂新代。"""
        with self._inbox_lock:
            self._gen += 1
            stale = [dict(e) for e in self._inbox if e.get("gen") != self._gen]
            if stale:
                self._inbox = [e for e in self._inbox if e.get("gen") == self._gen]
        for e in stale:
            self.emit({"kind": "input_discarded", "id": e.get("id"),
                       "reason": reason, "gen": e.get("gen")})
        self.sync_meta()
        return len(stale)

    def _queue_pump(self):
        """回合终结自动泵（#10）：800ms 延迟给 result 收尾/用户中断留窗
        口，再把当前世代队首真发（复用 send_message 全套守卫）。
        v3.4.54R（全审回炉）：_run **不再持 _busy_lock 包 send**——泵线程
        持 B 进 send 热更段取 _start_lock，与 kill_proc（持 S 取 B）构成
        AB-BA 死锁（reviewer 实证复现）。双泵互斥改由 pop 的 _inbox_lock
        原子争夺天然闭合：拿到条目者发、拿不到者让位；busy 竞争由
        send_message 自身的 CAS（_busy_lock）裁决，被拒即回插，消息保命。
        v3.4.76R：_arm 统一挂 timer（_inbox_lock 内 CAS——复核问题三的
        None→t 窗口双链不合并竞态收口）。"""
        def _arm(delay):
            # CAS 挂 timer：已有挂起 timer 即让位（不叠链）；已删会话不挂（R1）
            with self._inbox_lock:
                if self._closed or self._pump_timer:
                    return
                t = threading.Timer(delay, _run)
                t.daemon = True
                t.start()
                self._pump_timer = t

        def _run():
            with self._inbox_lock:
                self._pump_timer = None
            try:
                if self.busy:
                    # v3.4.76（用户实锤「排队消息永不发送」）：busy 期不再静默
                    # 放弃——泵到点恰逢下一回合已起（CLI 自发续跑/新消息竞速）
                    # 是常态，旧实现一次错过即滞留。3s 周期重试至 busy 翻
                    # false；inbox 无当前代条目则不挂（空转消散——复核问题二）
                    with self._inbox_lock:
                        _pending = any(e.get("gen") == self._gen
                                       for e in self._inbox)
                    if _pending:
                        _arm(self._PUMP_RETRY)
                    return
                with self._inbox_lock:
                    if not self._inbox:
                        return
                    idx = next((i for i, e in enumerate(self._inbox)
                                if e.get("gen") == self._gen), None)
                    if idx is None:
                        return
                    e = dict(self._inbox.pop(idx))
                self.emit({"kind": "input_promoted", "id": e.get("id")})
                ok, _err = self.send_message(e.get("text") or "",
                                             e.get("images"), e.get("files"))
                if self._closed:
                    # R1：pop 后 close 竞速——条目随删作废，不 revive/不挂链/
                    # 不回写账本（复核 RES：已删会话的 sync_meta 是复活写点）
                    return
                if not ok and self.session_id:
                    # v3.4.76R（复核问题一·用户实锤路径）：「立即发送」走
                    # interrupt→kill→进程死，send_message 必拒发（"会话进程
                    # 已退出"）——旧失败路径回插后无重试=永滞。先 revive（有
                    # session_id 可续上下文）再试一次；revive 持 _start_lock
                    # 与本线程无外层锁，安全
                    try:
                        if self.revive_if_dead():
                            ok, _err = self.send_message(
                                e.get("text") or "", e.get("images"),
                                e.get("files"))
                    except Exception:
                        pass
                if not ok:
                    # 失败回插队首 + 重发 admitted 事件——前端把条目加回
                    # 队列 UI（可见可删）；不 emit input_discarded（原「作废」
                    # 语义曾在竞态下吞消息）。世代校验：泵发送期间恰逢 /rewind
                    # 换代，旧代条目按换代作废语义显式 discard
                    if e.get("gen") != self._gen:
                        self.emit({"kind": "input_discarded", "id": e.get("id"),
                                   "reason": "rewind", "gen": e.get("gen")})
                    else:
                        with self._inbox_lock:
                            self._inbox.insert(0, e)
                        self.emit({"kind": "input_admitted", "id": e.get("id"),
                                   "text": (e.get("text") or "")[:200],
                                   "gen": e.get("gen"),
                                   "att": len(e.get("images") or [])
                                         + len(e.get("files") or [])})
                        # v3.4.76R2（R2 分类闸）：仅瞬态失败挂 3s 重试——
                        # 超窗类持久拒发（_err 含「窗口」）不挂（每 3s 事件/
                        # 落盘/UI 闪烁无限循环+GC 杀拉锯战），静默等用户
                        # /rewind、/compact 或下回合终结再试；连续失败 ≥5 次
                        # 也停挂（未知持久错兜底），成功发送即清零
                        self._pumpFailN += 1
                        _errS = str(_err or "")
                        if ('窗口' not in _errS) and self._pumpFailN < 5:
                            _arm(self._PUMP_RETRY)
                if ok:
                    self._pumpFailN = 0
                if not self._closed:   # 复核 RES：已删会话不回写账本
                    self.sync_meta()
            except Exception:
                pass

        _arm(self._PUMP_DELAY)

    # ---- 子代理镜像事件（#12，v3.1）----
    def _emit_task_mirror(self, o):
        """CLI 杂讯 → 干净生命周期事件。前端 handleEvent 的 20 段 Task
        解析（协作包装/转交线/段壳）保持不动——镜像事件只喂 reducer 投影
        （新进程面板与回合摘要行），live/重放共用同一份干净契约。"""
        sub = o.get("subtype")
        tid = str(o.get("tool_use_id") or "")
        if not tid:
            return
        if sub == "task_started":
            self.emit({"kind": "subagent_started", "tid": tid,
                       "agent_type": o.get("subagent_type") or "Task",
                       "desc": str(o.get("description") or "")[:200],
                       "bg": bool(o.get("is_backgrounded")),
                       "task_id": str(o.get("task_id") or "")})
        elif sub == "task_notification":
            usage = o.get("usage") or {}
            st = str(o.get("status") or "")
            self.emit({"kind": "subagent_result", "tid": tid,
                       "ok": st in ("", "completed", "success"),
                       "brief": str(o.get("summary") or "")[:200],
                       "tokens": usage.get("total_tokens") or 0,
                       "tool_n": usage.get("tool_uses") or 0,
                       "task_id": str(o.get("task_id") or "")})

    # ---- 事件层 ----
    def _check_peer_lines(self):
        """跨会话回传检测（v2.27.4）：CLI 收到 peer 消息只写转写 jsonl，
        不往 stdout 流吐 user 事件（实测事件缓冲里 495 条 system 全是
        thinking_tokens，零 peer 信号）——前端永远看不到回传。这里在回合
        有输出（assistant/result 事件）时增量扫转写尾部，新出现的 peer
        行（origin.kind=peer）先于该事件下发 kind:'peer'，前端渲染📥气泡。
        首次调用只建立偏移基线（跳过历史），之后每次只读新增字节。"""
        try:
            if not self.session_id:
                return
            # v2.27.20：reader 线程与回传兜底轮询线程都会进来——锁住防偏移
            # 竞争重复 emit（两线程同时读同一段增量，peer 气泡画两份）。
            # v2.3.2 审计 P7：换代重置（_tr_sid 比对+三字段清空）也挪进锁内——
            # 原在锁外，线程 B 清空 _tr_off 后，锁内读到一半的线程 A 用
            # f.tell() 把 None 覆写回旧文件偏移，旧偏移对着新文件用（错位/漏行）
            with self._tr_lock:
                # v2.27.20：session_id 变了（超窗续命换代 / resume 分叉）——缓存
                # 的转写路径还指着旧文件，新文件的 peer 行永远扫不到（换代后
                # 回传"凭空消失"的第二个根因）。归属不符即作废重找、重立基线。
                if getattr(self, "_tr_sid", None) != self.session_id:
                    self._tr_sid = self.session_id
                    self._tr_path = None
                    self._tr_off = None
                if not getattr(self, "_tr_path", None):
                    import glob as _g
                    for cand in _g.glob(os.path.join(os.path.expanduser("~"),
                                         ".claude", "projects", "*", self.session_id + ".jsonl")):
                        self._tr_path = cand
                        break
                path = getattr(self, "_tr_path", None)
                if not path:
                    return
                try:
                    size = os.path.getsize(path)
                except OSError:
                    # v2.27.20：转写文件被清理（外部清缓存等）——清缓存下轮
                    # 重找，别每 5s 抛一次被吞的异常空转
                    self._tr_path = None
                    return
                off = getattr(self, "_tr_off", None)
                if off is None:            # 基线：从文件末尾起，历史 peer 不重放
                    self._tr_off = size
                    return
                if size < off:             # 截断/轮转 → 重扫全量
                    off = 0
                if size == off:
                    return
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(off)
                    chunk = f.read()
                    self._tr_off = f.tell()
            for ln in chunk.splitlines():
                ln = ln.strip()
                if not ln or ("Another Claude" not in ln and '"peer"' not in ln):
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                if o.get("type") != "user":
                    continue
                t = (o.get("message") or {}).get("content")
                # v2.3.2 两形态（用户实锤「模型收到了前台没显示」）：
                # 独立行=空闲期到达，origin.kind=peer、正文以标记开头（原逻辑）；
                # 内嵌行=busy 期到达被 CLI 排队，回合结束注入进下一轮用户消息
                # （system-reminder 包装，origin 是 human）——此前检测不到，
                # 模型收到了但前端永远无气泡。走到这里的含标记 user/str 统一解析
                # （内嵌型须带 <cross-session-message 标签收窄，防用户手打误报）。
                if not isinstance(t, str) or \
                        "Another Claude session sent a message" not in t:
                    continue
                if (o.get("origin") or {}).get("kind") != "peer" and \
                        "<cross-session-message" not in t:
                    continue
                # v2.3.2 审计 1a 误报收窄：非 peer origin（内嵌型）还须 system-reminder
                # 壳在标记之前——CLI 排队注入的固定形态；用户手贴回传原文/贴原始
                # jsonl 排查问题时通常不带这层壳，不再弹假回传气泡
                _mp = t.find("Another Claude session sent a message")
                if (o.get("origin") or {}).get("kind") != "peer" and _mp > 0:
                    if t.find("<system-reminder") < 0 or \
                            t.find("<system-reminder") > _mp:
                        continue
                nm = re.search(r'from-name="([^"]*)"', t)
                body = re.search(r"<cross-session-message[^>]*>(.*)</cross-session-message>",
                                 t, re.S)
                # v2.27.5：peer 消息会触发自动回合，但没走 harness send()——
                # busy 从未被置起，活动指示条不亮（用户实锤）。这里补置，
                # result 事件照常回落；前端 5s 轮询据此亮指示条+计时。
                # v2.27.19：只在进程活着时置——死会话（回传兜底轮询扫到的）
                # 没有 result 来回落，置了会永远挂「回复中」
                if self.alive:
                    with self._busy_lock:      # v3.4.54：置位同步入锁
                        self.busy = True
                        self.busy_since = int(time.time() * 1000)
                    self._turn_start()
                self.emit({"kind": "peer",
                           "name": nm.group(1) if nm else "其他会话",
                           "text": ((body.group(1) if body else t).strip())[:8000]})
        except Exception:
            pass

    def _relay_vision_reply(self, o):
        """v2.3.2：识图会话回传代播——它的 assistant 事件流里出现 SendMessage
        tool_use 时，把结论（input.message）直接广播给所有主会话（emit kind='peer'
        附 to=收件人 peer 名）。主会话 busy 时 CLI 运行时注入不留 jsonl 痕迹，
        这是唯一可靠的观测点。前端按转交线收件人名匹配渲染，错发无污染。"""
        try:
            blocks = (o.get("message") or {}).get("content") or []
            if not isinstance(blocks, list):
                return
            for b in blocks:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"
                        and b.get("name") == "SendMessage"):
                    continue
                inp = b.get("input") or {}
                to = str(inp.get("to") or "")
                msg = str(inp.get("message") or "").strip()
                if not msg:
                    continue
                name = getattr(self, "name", None) or "识图会话"
                with _sessions_lock:
                    targets = [s for s in _sessions.values()
                               if not getattr(s, "is_vision", False)]
                for s in targets:
                    s.emit({"kind": "peer", "name": name, "to": to,
                            "text": msg[:8000]})
        except Exception:
            pass

    def _reader_loop(self):
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line_b in proc.stdout:
                if not self.alive:
                    break
                line = line_b.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self.last_active = int(time.time() * 1000)
                try:
                    o = json.loads(line)
                except Exception:
                    self.emit({"kind": "raw", "text": line})
                    continue
                typ = o.get("type")
                # v2.3.0：thinking_tokens 进度心跳不转发——CLI 思考期间逐条推
                # 「已思考约 N tokens」（每秒 1~3 条），前端零消费（活动指示条
                # 计时是前端自算），但每条都要 SSE 推送+前端 parse+分派再丢弃，
                # 且刷爆 4000 条事件缓冲把有价值的重放事件挤出去（实测单会话
                # 缓冲 495 条全是它）。思考内容（thinking 块）/回复文本（text
                # 块）走完全不同的事件，不受影响。
                if typ == "system" and o.get("subtype") == "thinking_tokens":
                    continue
                if typ == "system" and o.get("session_id") and o.get("subtype") == "init":
                    if o.get("session_id") != self.session_id:
                        self.session_id = o.get("session_id")
                        self.sync_meta()
                    # v2.35（P0-1 根因修复）：CLI 自发回合（后台任务完成通知、
                    # 协作回传续跑等）不经 send()，busy 从未被置起——事件流里
                    # 模型在干活、会话列表却报空闲，前端 5s 自愈轮询据此把运行
                    # 态徽章摘掉（用户实锤「AI 还在执行运行状态没了」），排队泵
                    # 还会提前把队列消息打进正在跑的回合。stream-json 实测
                    # （stdin 保持打开）：每回合起跑都发一条 system/init，首个
                    # init 是进程待机（不能置，否则空转进程永远挂「回复中」），
                    # 第 2 个起即新回合——此刻补置 busy，回合终结的 result 照常
                    # 回落。revive/热更重启的「新进程首 init」不置：该路径随后
                    # 必有 send() 占位，不靠这里。
                    self._init_n = getattr(self, "_init_n", 0) + 1
                    if self._init_n > 1 and self.alive and not self.busy:
                        with self._busy_lock:  # v3.4.54：置位同步入锁
                            self.busy = True
                            self.busy_since = int(time.time() * 1000)
                        self._turn_start()
                # v2.35（P0-1 兜底）：主链 assistant 事件到达而 busy 仍 False =
                # 一条我们没观察到起点的回合正在跑（init 丢失/旧版 CLI 无续
                # init）——同样补置。子代理事件（带 parent_tool_use_id）不算：
                # 后台子代理跑活时主会话本就空闲、可以收新消息。
                if typ == "assistant" and not o.get("parent_tool_use_id") \
                        and self.alive and not self.busy:
                    with self._busy_lock:      # v3.4.54：置位同步入锁
                        self.busy = True
                        self.busy_since = int(time.time() * 1000)
                    self._turn_start()
                if typ == "result":
                    with self._busy_lock:      # v3.4.54：回落同步入锁（sync_meta 锁外）
                        self.busy = False
                    self.last_result = o
                    # v2.2.1：回合结束落一次盘——last_active 平时只更新内存，
                    # 重启工具后 meta 停在旧时刻会话排序/时间倒退（回合粒度
                    # 写盘，频次可接受；每行写则太频）
                    try:
                        self.sync_meta()
                    except Exception:
                        pass
                if typ == "user":
                    # v2.50（P1）：Task 派发的 result 到达时回填 agentId→
                    # 角色映射（SendMessage 续派按裸 agentId 寻址的结算口径）
                    try:
                        self._audit_tally_result(o)
                    except Exception:
                        pass
                if typ == "assistant":
                    # v2.27.21：记录 CLI 实报模型名——引导词热更/窗口判定
                    # 的第一依据（settings 名会与实跑名错位，见 _eff_model）。
                    # 只记录不打断：若与注入词的三态分类不一致，下一次 send
                    # 前的 bridge_fp 热更自然发现指纹变化并换词重启
                    lm = (o.get("message") or {}).get("model")
                    if lm and lm != self.live_model:
                        self.live_model = lm
                        self.sync_meta()
                    # v2.3.2 第三形态（用户实锤「识图跑完回传没显示」）：目标
                    # 会话 busy 时，CLI 把回传以运行时通知直接注入其当前回合，
                    # **jsonl 零痕迹**——主会话侧扫盘永远无解。改在识图会话侧
                    # 截获：它发出的 SendMessage tool_use（input.to/message 现成）
                    # → 向全部非 vision 会话广播 kind='peer'（带 to 字段），前端
                    # 按转交线上的收件人名对号入座渲染，无污染。
                    if getattr(self, "is_vision", False):
                        self._relay_vision_reply(o)
                    # v2.34：回合内审计累计（纯计数零盘 IO；子代理事件内部
                    # 自行排除，见 _audit_tally）
                    self._audit_tally(o)
                if typ in ("assistant", "result"):
                    self._check_peer_lines()   # 回合有输出 → 先补发新到的 peer 回传
                # v3.1（#12）：Task 生命周期系统事件 → 干净镜像事件（reducer/新面板用）
                if typ == "system" and o.get("subtype") in ("task_started",
                                                            "task_notification"):
                    try:
                        self._emit_task_mirror(o)
                    except Exception:
                        pass
                self.emit({"kind": "event", "data": o})
                # v2.34：result 即回合终点——结算审计（light 形态违规兜底，
                # 事件已 emit，前端先收 result 收尾再收审计警示，顺序自然）
                if typ == "result":
                    try:
                        self._audit_settle("result")
                    except Exception:
                        pass
                    self._turn_end()
        except Exception:
            pass
        finally:
            was_busy = self.busy    # v2.34：进程死时回合是否仍在进行（下方结算用）
            # 身份校验：kill+立即 revive（切模型/base_url 自愈/引导词热更都
            # 是同线程 kill 后马上 start）时，旧 reader 排空剩余 stdout 可能
            # 晚于新 start() 完成——不校验会把新进程的 alive/busy 打死，下一
            # 次 send 又 revive，多 spawn 一个孤儿进程
            if proc is self._proc:
                self.alive = False
                with self._busy_lock:      # v3.4.54：置位同步入锁
                    self.busy = False
            # v2.40：自然死亡不走 kill_proc——事中闸 settings 临时文件在这
            # 条路径也要清（否则 revive 覆盖引用后旧文件泄漏，见方法注释）
            self._audit_settings_cleanup()
            # v2.20：计划内重启（会话内切模型）吞掉 exit——只吞一次，
            # 防止标志位残留吞掉真正的意外退出
            if getattr(self, "_suppress_exit", False):
                self._suppress_exit = False
            else:
                # v2.34：回合进行中进程死掉（崩溃/被杀）——结算审计只警示
                # 不续发（进程已死）。was_busy 在 busy 复位前取：kill_proc
                # 会先把 busy 清掉，正常 result 后的进程退出不算「回合中断」。
                # v3.4.54R（全审回炉）：结算只认当代 reader——kill 时进程已
                # 死透（_suppress_exit 未设）且旧 reader 排空跨越 revive+新
                # 回合的窄窗里，旧 reader 会拿新回合的 was_busy 误结算审计/
                # 误发 turn_error；exit 行保持原位（GC 裸杀仍有提示）
                if was_busy and proc is self._proc:
                    try:
                        self._audit_settle("exit")
                    except Exception:
                        pass
                    self._turn_end(err=True)
                self.emit({"kind": "exit", "text": "会话进程已结束（发送消息将自动恢复）"})
                _trace_append(self.sid, "exit",
                              "会话进程已结束（发送消息将自动恢复）")   # v3.4.87：同上

    def _drain_stderr(self):
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                if not self.alive:
                    break
                txt = line.decode("utf-8", errors="replace").strip()
                if not txt:
                    continue
                # v2.13：CLI stderr 良性日志过滤——unrecognized_model 是 CLI
                # 对非内置名（Lanz-*）的提醒，模型实际回退默认照常跑（实测 rc=0
                # 输出正常）；原样 emit 成 raw 事件会在界面显示红字，用户实测
                # 误以为是模型失效。真失效走 API 400（result 事件已有独立提示）。
                if "unrecognized_model" in txt or "claude-code:" in txt and "warning" in txt.lower():
                    continue
                self.emit({"kind": "raw", "text": txt})
        except Exception:
            pass

    # ---- 交互式提问（v2.17）----
    def ask_open(self, req_id, title, questions):
        """登记一个待答问题并广播 harness_ask 事件（前端渲染可点卡片）。

        同一会话同时只允许一个待答问题：模型是串行调用的，若旧的还没答
        又来一个，说明旧的那个已经没意义了（工具调用已被中断等），直接换掉。
        """
        with self.ask_lock:
            self.ask = {"req_id": req_id, "title": title,
                        "questions": questions, "answer": None,
                        "done": False, "ts": int(time.time() * 1000)}
        self.emit({"kind": "ask", "req_id": req_id, "title": title,
                   "questions": questions})
        return True

    def ask_answer(self, req_id, answer):
        """用户提交答案：记下并唤醒长轮询中的 MCP 工具调用。"""
        with self.ask_lock:
            a = self.ask
            if not a or a.get("req_id") != req_id:
                return False
            a["answer"] = answer
            a["done"] = True
        self.emit({"kind": "ask_done", "req_id": req_id, "answer": answer})
        return True

    def ask_poll(self, req_id):
        """MCP 侧长轮询：返回 (found, done, answer)。

        v3.4.61：req_id 为空 = 前端快照语义——返回当前待答问题的完整
        快照（含 questions 题面）。冷开/transcript 重建路 seq 已跳过 ask
        帧（不重放），前端靠此拉回面板。MCP 侧恒传 req_id，行为不变。
        """
        with self.ask_lock:
            a = self.ask
            if not a or a.get("req_id") != req_id:
                return False, False, None
            return True, bool(a.get("done")), a.get("answer")

    def ask_snapshot(self):
        """待答问题全量快照（前端 _hgAskSync 冷开恢复用）：(found, dict|None)。

        返回的 dict 含 req_id/title/questions/done/answer——已答的也返回
        （done=True），供他窗已答场景走 askDone 收面板；无待答记录返回
        (False, None)。"""
        with self.ask_lock:
            a = self.ask
            if not a:
                return False, None
            return True, {"req_id": a.get("req_id"), "title": a.get("title"),
                          "questions": a.get("questions") or [],
                          "done": bool(a.get("done")), "answer": a.get("answer")}

    def ask_cancel(self):
        """会话进程结束/被中断：让还在等的 MCP 调用立刻拿到「用户未作答」，
        不要继续空转轮询。"""
        with self.ask_lock:
            a = self.ask
            if a and not a.get("done"):
                a["answer"] = {"_cancelled": True}
                a["done"] = True
            self.ask = None

    # ---- v3.0 回合边界 ----
    # turn 的显式化：此前回合边界靠 data.type=='result' 隐式判定（前端
    # _hgTurnEnd / 后端 busy 旗各自补），是「事件不完整导致的补丁」典型。
    # 现在起跑（send 占位/CLI 自发回合/peer 续跑）与收尾（result/中断/退出）
    # 都发 turn_* 事件；信封 turn 字段随行。前端本期忽略（未知类型静默跳过），
    # reducer 已消费。
    def _turn_start(self):
        if self._turn_id:
            return
        self._turn_id = new_turn_id()
        self.emit({"kind": "turn_started"})

    def _turn_end(self, err=False):
        # 注：_interrupt_async 在 reader 线程之外调；_run 泵事务持锁重入
        # _turn_end 的路径已随 v3.4.54R 泵改造移除（防 AB-BA 死锁），RLock
        # 保守保留——勿依赖重入语义新增持锁调用
        had = bool(self._turn_id)
        if had:
            self.emit({"kind": "turn_error" if err else "turn_complete",
                       "text": "回合异常收尾" if err else ""})
            self._turn_id = None
        # v3.1（#10）：回合终结 → 自动泵排队输入（延迟 800ms，见 _queue_pump）
        # v3.4.76（用户实锤「排队消息永不发送」）：泵调用移出 _turn_id 早退
        # ——turn_id 单槽在回合交错（A result 迟到清掉 B 的 id / B 终结时
        # 已为 None）时真正该泵的那次早退，泵永不触发。幂等：timer 单例+
        # 空 inbox+busy 检查三重守卫，重复调用无害
        try:
            self._queue_pump()
        except Exception:
            pass

    def emit(self, item):
        """事件唯一出口：截断→锁内盖章→落 store→广播（对照 ZCode「先落
        eventStore 再广播 eventSinks」）。seq 分配在 store 锁内——修 v2.x
        reader/HTTP/peer 轮询并发 emit 的同号乱序竞态。"""
        item = self.log.emit(item, turn=self._turn_id)
        return item

    def get_events_after(self, after_seq=0, limit=500):
        return self.log.events_after(after_seq, limit=limit)

# ---- from claude_harness.py:2842 (_session_ctx_used) ----


def _session_ctx_used(s):
    """会话已用上下文 tokens（/ctx 与 set_model 窗口预检共用）。
    取值顺序：jsonl 尾部倒扫最新非零 usage（跳过子代理行；撞压缩边界
    归零——/compact 后旧值全部过期）→ last_result.usage 兜底。
    last_result 只贡献窗口（contextWindow）。返回 (used, window, compacted)。"""
    used, window = 0, 0
    lr = getattr(s, "last_result", None) or {}
    try:
        mu = lr.get("modelUsage") or {}
        for k in mu:
            w = (mu[k] or {}).get("contextWindow") or 0
            window = max(window, int(w))
        u = lr.get("usage") or {}
        used = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
            + (u.get("cache_creation_input_tokens") or 0)
    except Exception:
        used = 0
    import glob as _glob
    path = None
    proj = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    for cand in _glob.glob(os.path.join(proj, "*", s.session_id + ".jsonl")):
        path = cand
        break
    found = False
    compacted = False
    if path:
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 1048576))     # 尾部 1MB（大行/多附件保险）
                tail = f.read().decode("utf-8", errors="replace")
            for raw in reversed(tail.splitlines()):
                raw = raw.strip()
                if '"isCompactSummary":true' in raw:
                    if not found:
                        compacted = True
                        used = 0
                    break
                if '"type":"assistant"' not in raw or '"usage"' not in raw:
                    continue
                if '"isSidechain":true' in raw:
                    continue
                try:
                    o = json.loads(raw)
                except Exception:
                    continue          # 块首半行被截断，跳过
                uu = (o.get("message") or {}).get("usage") or {}
                v = (uu.get("input_tokens") or 0) + (uu.get("cache_read_input_tokens") or 0) \
                    + (uu.get("cache_creation_input_tokens") or 0)
                if isinstance(v, int) and v > 0:
                    used = v
                    found = True
                    break
        except OSError:
            pass
    return used, window, compacted

# ---- from claude_harness.py:2901 (_CTX_WINDOW_1M) ----


# 网关模型上下文窗口（tokens）：模型名带 [1M] 后缀 = 1M 窗口变体，
# 其余默认 256K（实测报错原文 maximum context length 262144）。
_CTX_WINDOW_1M = 1048576

# ---- from claude_harness.py:2906 (_CTX_WINDOW_DEFAULT) ----
_CTX_WINDOW_DEFAULT = 262144

# ---- from claude_harness.py:2907 (_session_ctx_window) ----


def _session_ctx_window(s):
    """v2.27.22：会话上下文窗口——候选链解析 [1M] 后缀：会话配置名 →
    settings 默认名 → CLI 实报名。实报名（live_model，网关上报）会被
    剥掉 [1M] 后缀（裸 glm-5.3），单看它会把 1M 会话判成 256K →
    251K 被误判超窗拒发（用户实锤「严重 bug」）。窗口是用户在配置里
    显式选的后缀属性，必须从配置名读；实报名只作最后兜底。"""
    for n in (s.model, available_models().get("default"), s._eff_model()):
        n = (n or "").lower()
        if "[1m]" in n or n.endswith("1m"):
            return _CTX_WINDOW_1M
    return _CTX_WINDOW_DEFAULT
