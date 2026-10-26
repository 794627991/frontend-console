# -*- coding: utf-8 -*-
"""v4 投影 feed：CLI 事件 → 行 delta 归约 + delta log + 订阅帧（拉模式）。

对照 ZCode bootstrap/zcode-protocol-v4/{product-projection,
conversation-topic-publisher}.ts 的 SSE 化移植（v4 线，2026-10-20 重构）：

- V4Feed 每会话一只（主会话 + 每个子代理各一只）。ingest(env) 把信封
  事件归约成封闭五操作 delta，用 v4proto.apply 推进自身快照（投影与
  delta 流逐字节一致是构造保证——服务端快照就是 apply 的产物）。
- 发布采用「共享 delta log + 订阅者游标」而非逐订阅者 push buffer：
  SSE 生成器每 30ms（FLUSH_MS）拉 frames_after(sent_seq)，对区间内 delta
  做 coalesce 打一帧。订阅者落后越出保留窗（floor）→ 拉 None → 发
  snapshot 帧重对齐（服务端单方裁决整窗替换，客户端没有猜结构路径）。
- 挂接顺序（persist-before-publish）：HarnessSession.emit → log.emit
  （store 锁内 seq 落账）→ 本 feed.ingest(env)。前端永远只消费投影。
- epoch：/rewind bump_epoch 时 feed 重建（_reset），旧订阅携旧 epoch
  重连只能拿 snapshot。
- 子代理 feed（V4AgentFeeds）：watcher 扫描 CLI 子代理转写 jsonl 的增量
  行 → feed_jsonl_line 归约入子投影；首次访问（hydrate）从文件全量重建。
  子投影与主投影共用 V4Feed 的行模型与帧协议——子 pane 与主窗口同管线。

行粒度对齐（.hg-unify-plan.md 核对结论）：assistant text/thinking 块级
一行；tool_use 一行、tool_result 终态 upsert；CLI 不开 partial 流式，
文本块一次到达（row.delta 预留流式能力，当前主要消费方是 coalesce 后
的批量 append——协议位留足，CLI 开 partial 即生效）。
"""
import bisect
import json
import logging
import os
import re
import threading
import time
import uuid

from . import v4proto as P

log = logging.getLogger(__name__)

# hand-back aid 提取的单一正则（F1 第二缺陷）：真实转写形态是
# `<agent-message from=\"a4ec4a0433c71b3f4\">`（等号+引号，JSON 内转义），
# 旧口径 `from "X"`（空格+引号）在 1173 条真实样本上命中 0。
# session.py:_HB_AID_RE 必须与本式同源（跨模块文本一致，勿单改一处）。
HB_AID_RE = re.compile(r'from[=\\" ]+([0-9a-zA-Z_-]{8,64})')

FLUSH_MS = 30                  # 订阅帧合并窗口（ZCode continuous profile）
LOG_RETAIN = 600               # delta log 保留条数（越窗订阅者转 snapshot）
# a41c 退役：TAIL_ROWS 行数闸删除（与回合窗并存必打架，见 snapshot_wire
# 注释）；wire_snapshot 的 tail 参数保留仅供单测直接调用


def _txt(content):
    """CLI content 块列表 → 纯文本（str 直通；list 拼 text 块）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
        return "\n".join(parts)
    return ""


_BG_ACK_RE = re.compile(
    r"^\s*(?:Async\s+)?agent\s+launched\s+successfully"
    r"|^\s*\{[^\n]{0,40}\"?agentId\"?\s*:", re.I)


def is_bg_ack(text):
    """后台派发回执判据（P1-7 / FATAL-2 单点）。真实回执两种形态：
    ① "Async agent launched successfully. (This tool result is internal
    metadata and not a final result)…"
    ② JSON 对象 `{"agentId": "...", "status": "success"}`。
    MAJOR-7 修正（a116 三次全审）：**必须行首锚定**。原实现是三串任意
    子串匹配，审计/复盘类结论里**提到** "launched successfully"、
    "for internal use" 的文本会被误判成 ACK → 真完成卡永久 running、
    秒表永跑（当前 310 条语料侥幸 0 误判，但只要子代理结论引用了 CLI
    回执就会中招）。v4feed live 与 v4hub hydration 同用本函数。"""
    return bool(_BG_ACK_RE.search(str(text or "")[:400]))


_HB_META_PREFIXES = (    # S7 修复（a116）：元数据判定单点。真实转写里有两种投递元数据文案
    # （CLI 版本差异），且**多数带 2 空格缩进**——旧实现用 startswith
    # 直接判，对 36/42 条真实样本失效（v4hub 与 v4feed 还各持一套字面量，
    # CLI 改文案即分头失效）。统一到本函数，调用方一律先 strip。
    "This agent's report was delivered",
    "The agent's report was delivered",
    "delivered to you as a message from",
)


def hb_is_meta(text):
    """hand-back/任务回执文本是否为「投递元数据」而非真结论。
    一般9 修正（a116 全审）：原实现含 `p in s[:200]`，把真结论正文里
    **提到**该短语的文本也判成元数据丢弃（实测
    '✅ 结论：CLI 打印了 delivered to you as a message from x' → True）。
    只保留 strip 后 startswith：只有整段以元数据前缀开头的才是 CLI 的
    投递说明。"""
    s = str(text or "").strip()
    return any(s.startswith(p) for p in _HB_META_PREFIXES)


def hb_report_body(t):
    """a81：hand-back 注入消息 → 报告正文。CLI 注入的固定安全前言（The
    text below is the final report...The report follows:）与每行 2 空格的
    防伪缩进都不是结论内容，剥掉；闭合标签同剥。"""
    import re as _re
    body = str(t or "").split("[Subagent hand-back]", 1)[-1]
    body = body.split("</agent-message>", 1)[0]
    if "The report follows:" in body[:600]:
        body = body.split("The report follows:", 1)[1]
    body = _re.sub(r"(?m)^  ", "", body)
    return body.strip()


def _input_brief(inp, limit=2000):
    """tool_use input → 展示用摘要 JSON（保序截断）。"""
    try:
        s = json.dumps(inp, ensure_ascii=False)
    except Exception:
        s = str(inp)
    return s[:limit]


def _in_obj(inp, cap=4000):
    """tool_use input → 可渲染对象（浅拷贝，超长字符串值截断防爆）。"""
    if not isinstance(inp, dict):
        return {}
    out = {}
    for k, v in inp.items():
        if isinstance(v, str) and len(v) > cap:
            out[k] = v[:cap] + "…"
        else:
            try:
                json.dumps(v, ensure_ascii=False)
                out[k] = v
            except Exception:
                out[k] = str(v)
    return out


class V4Feed(object):
    """单会话投影 feed（主会话与子代理共用）。线程安全：ingest 与取帧
    并发（ingest 来自 session 线程，取帧来自 SSE 生成器），锁内推进。"""

    # F1-R（a116 十一次全审）：**进程级** wseq 高水位。任何实例分配 wseq
    # 都在此推进，任何新实例的起点都不低于它 +1。这样「重建后旧游标落在
    # 新空间」在定义上不可能——不需要靠调用方推算偏移（账本 seq 与 wseq
    # 同额增长时，任何固定偏移都会在某个 k 上撞出等号边界）。
    # N3（十二次全审）：按 **epoch 分桶**。全局单桶会让活跃会话把无关
    # 会话的起点推得虚高（审计实测 A 写 100k 后 B 的 base=100001），
    # 数值失真且放大排查难度。桶键 = epoch（同会话重建时 epoch 相同，
    # 正是需要单调续号的场景）。
    _hwm = {}
    _hwm_floor = 0          # 桶淘汰时的全局兜底（被淘汰桶的最大值）
    _hwm_lock = threading.Lock()
    # 二十一次全审（严重，墙钟回拨）：墙钟**可回拨**（NTP 校时/手动改钟），
    # 而回拨量落在「重启耗时 E」的邻域内时，新 base 会掉到旧游标下方 →
    # 旧游标被判可续传 → 整批消息静默丢失（实测 R ∈ (E - m·1µs, E] 命中）。
    # 修法：给序号空间加**持久化的启动序号**作高位——每次进程启动 +1，
    # 与时钟完全无关。`base = boot * STRIDE + (墙钟微秒 % STRIDE)`：
    #   * 跨重启：boot 递增 ⇒ base 至少跳 STRIDE，远超上代任何水位；
    #   * 同一启动内：低 STRIDE 位按墙钟微秒递增，仍单调；
    #   * 回拨：只影响低位（≤1e9 µs = 1000 秒），不可能跨过 boot 高位。
    _BOOT_STRIDE = 10 ** 9      # 一代内事件数 << 10 亿，绝不溢出
    # boot 上限：`boot * _BOOT_STRIDE + 低位` 必须严格 < 2^53。
    # **必须预留整个低位域**（低位取值 0..STRIDE-1）——初版只除了一次，
    # 导致 74.5% 的低位取值越界（实测 base=9007199400000002 > 2^53-1）。
    _BOOT_MAX = ((2 ** 53) - 1 - _BOOT_STRIDE) // _BOOT_STRIDE
    # 最终起点上限 = 2^53-1（JS Number 安全整数）。`_claim_base` 末尾对
    # max(guess, hi, floor, boot量) 统一兜底——guess 可能来自被污染的
    # 持久化文件（旧版 boot 用时间戳时留下的 ~1.79e18 大值）。
    # 最终起点上限，留 100 万条余量——钳制后还要继续 _commit 递增，
    # 顶格钳会让紧接着的第一条事件就重新越界。
    _BASE_MAX = (2 ** 53) - 1 - 10 ** 6
    _boot = None                # 进程内缓存的启动序号（None = 未初始化）
    _boot_lock = threading.Lock()

    def __init__(self, epoch="", hydrate=None, wseq_base=0):
        self._lock = threading.Lock()
        # 性能批（事件驱动订阅）：帧版本号 + 条件变量——ingest 落账 bump 版本
        # 并广播，SSE 生成器 wait_frames 阻塞等到有新帧（或对账/keepalive
        # 到点），空闲期零唤醒（原 sleep(0.03) 轮询每连接每秒醒 33 次）
        self._cv = threading.Condition()
        self._ver = 0
        self._wseq_base = self._claim_base(epoch, wseq_base)
        self._reset(epoch, hydrate)

    @classmethod
    def _claim_base(cls, epoch="", floor_guess=0):
        """领取本实例的 wseq 起点：**严格大于**任何旧游标可能落到的位置。

        三源取最大，再 +2：
          ① `floor_guess`（调用方提示，主 feed = 账本 last_seq）
          ② 同 epoch 桶的 hwm（本进程发过的最大值）
          ③ 全局兜底 `_hwm_floor`（桶被淘汰后的残留高水位）
        `floor_guess=0` 且无历史时取 0（首个实例从 1 起编，保持既有语义）。

        为什么是 **+2** 而不是 +1（十三次全审，F1-R 第三形态）：
        上一代的起点是 `上代账本水位 + 1`，它发过 m 个事件后游标 =
        `上代水位 + 1 + m`；而本代的账本水位 = `上代水位 + m`（每事件 +1）。
        于是「旧游标 == 本代账本水位 + 1」**恒成立**——+1 会稳定撞等号，
        且不随代数消散。+2 使 base = `当前水位 + 2` = 旧游标 + 1，恒安全；
        又因为每代都以**账本水位**为基准（不是在上代 base 上累加），
        偏移不会逐代膨胀。

        取等为什么危险：`_in_window` 的下界是 `_wseq_base`，游标 == 起点
        会被判可续传 → 重建后旧游标合法落进新空间 → 整段历史当增量重放
        → 前端 rowId 撞号、静默丢行（审计实测吞 10 行）。"""
        key = epoch or ""
        with cls._hwm_lock:
            hi = cls._hwm.get(key, 0)
            guess = int(floor_guess or 0)
            # 十八次全审（致命，偏移逐代累积）：`max(持久化值, 账本last_seq)`
            # 作为 hint 时，持久化一旦失效就退化为 last_seq，而 last_seq
            # 恒比上代水位小 offset —— offset 每代 +2 且不回退。几代之后
            # 旧游标（= 上代水位）会**同时**越过 `_wseq_base` 与
            # `_first_issued`，实测 16~20 条新消息静默丢失。
            # 根因：把「起点严格递增」寄托在**会被清零的外部状态**上。
            # 换用**与状态无关的单调源**：墙钟微秒。它跨进程、跨崩溃、
            # 跨 epoch 天然单调（除系统时钟回拨，见下），不依赖任何持久化
            # 文件是否可写。数值 1.79e15 < 2^53，JS Number 精确表示无虞。
            # 时钟回拨兜底：仍与进程内 HWM/提示取 max，保证本进程内不倒退。
            _wall = int(time.time() * 1000000)
            # 二十一次全审（严重）：墙钟可回拨 → 用**持久化启动序号**作高位。
            # 详见类属性 `_BOOT_STRIDE` 处的注释。低位取墙钟微秒对 STRIDE
            # 取模，保证同一启动内仍按墙钟递增；跨启动由 boot 递增保证跳变。
            _boot = cls._next_boot()
            _namespaced = _boot * cls._BOOT_STRIDE + (_wall % cls._BOOT_STRIDE)
            # 十九次全审（致命）：这里**不能**有 `return 0` 早退。
            # 原以为「本进程第一代 ⇒ 无旧游标」，但旧游标的真源不止 wseq
            # 文件——前端把游标存在 `localStorage['hg_v4snap:<sid>:main']`，
            # 与后端状态完全独立。后端全丢（进程重启 + 盘清 + meta 归零）
            # 而前端仍持游标时，三条件全 0 → base=0 → 新事件从 1 起编 →
            # 与旧游标空间重叠（实测主窗 5 条全丢；子 feed epoch 恒 "sub"，
            # 跨重启 300 行内容错位）。
            # `base=0` 的唯一用途是「客户端本地无内容」，而 routes 层
            # `base_seq > 0` 门已保证游标 0 不进 resume_probe——该语义多余。
            base = max(guess, hi, cls._hwm_floor, _namespaced) + 2
            # 二十三次全审（一般）：钳制此前只作用于 `_namespaced`（boot
            # 那一路）。升级自旧版（boot 曾用时间戳）遗留的 wseq 文件里
            # 可能存着 ~1.79e18 的大值，经 v4hub 的 `_hint` 注入 guess →
            # base 越过 JS 安全整数，前端 Number 低 3 位归零（实测
            # base=1792758829942572290 > 2^53-1）。且 `_save_wseq` 的
            # `v <= _wseq_written` 守卫会让该大值永远留在盘上。此处对
            # **最终 base** 统一做上限兜底（低位域已由 _BOOT_MAX 预留，
            # 正常路径不会触顶；触顶说明输入来自被污染的持久化数据）。
            if base > cls._BASE_MAX:
                log.warning("v4 wseq 起点越界 %s（来源 guess=%s hi=%s），"
                            "钳制到 JS 安全整数上限 %s",
                            base, guess, hi, cls._BASE_MAX)
                base = cls._BASE_MAX
            if base > hi:
                # LRU 语义：重插到末尾（dict 保序），淘汰时先删最久未用的
                cls._hwm.pop(key, None)
                cls._hwm[key] = base
            # 桶数无界防护：超 512 时淘汰**最久未用**的前一半，并把他们
            # 的最大值汇入全局兜底（单调不减）。
            if len(cls._hwm) > 512:
                _dead = list(cls._hwm)[:256]
                for _k in _dead:
                    _v = cls._hwm.pop(_k, 0)
                    if _v > cls._hwm_floor:
                        cls._hwm_floor = _v
            return base

    @classmethod
    def _next_boot(cls):
        """本进程的启动序号（进程内只算一次，之后缓存）。

        **持久化的**单调计数器：进程启动时读文件 +1 写回。与时钟无关，
        因此 NTP 校时/手动改钟的回拨不可能让它倒退。
        写失败时退化为「墙钟秒」（仍单调，只是不再跨重启保证），并打一次
        告警——不阻塞会话创建。
        """
        if cls._boot is not None:
            return cls._boot
        with cls._boot_lock:
            if cls._boot is not None:
                return cls._boot
            path = cls._boot_path()
            cur = 0
            try:
                with open(path, encoding="utf-8") as f:
                    cur = int((f.read() or "0").strip() or 0)
            except Exception:
                cur = 0
            # 二十二次全审（致命，我自己引入的）：boot **必须是小序号**。
            # 初版 `max(cur, int(time.time())) + 1` 让 boot ≈ 1.79e9，于是
            # `base = boot*1e9 + 低位` ≈ 1.79e18 —— 超出 JS 安全整数
            # 9.007e15 两百倍，前端 Number 精度丢失（低 3 位归零），
            # 游标比较/判等全部失真。
            # 改用纯小序号：从 1 起编，每次启动 +1。它只需要「跨重启严格
            # 递增」，不需要任何时间含义。
            # 二十二次全审（严重）：BOOT 文件被清/损坏时回落到「现存 wseq
            # 文件的最大 boot 头」——否则 boot 归 1，在时钟回拨叠加时起点
            # 会掉到旧游标下方（实测 gap -6000 万，靠 `seq > water` 侥幸挡）。
            nxt = max(cur, cls._boot_floor_from_wseq()) + 1
            # 二十二次全审（一般）：BOOT 文件被写入极大值时（损坏/人为），
            # `boot*1e9` 会逼近甚至超出 JS 安全整数 2^53。钳到
            # `_BOOT_MAX`（2^53 // 1e9 = 9007199），对应 base 上限约 9.0e15。
            if nxt > cls._BOOT_MAX:
                try:
                    log.warning("v4 BOOT 计数超出安全范围 %s，钳制到 %s",
                                nxt, cls._BOOT_MAX)
                except Exception:
                    pass
                nxt = cls._BOOT_MAX
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(str(nxt))
                os.replace(tmp, path)
            except Exception:
                try:
                    log.warning("v4 boot 序号落盘失败 path=%s；跨重启单调"
                                "退化为墙钟秒（回拨风险复现）", path,
                                exc_info=True)
                except Exception:
                    pass
            cls._boot = nxt
            return nxt

    @classmethod
    def _boot_floor_from_wseq(cls):
        """BOOT 文件被清/损坏时的兜底：扫现存 wseq 文件，取它们隐含的
        boot 高位（`值 // _BOOT_STRIDE`）的最大值。这样即使 BOOT 丢失，
        只要还有任一会话的 wseq 文件，新 boot 也不会低于上一代。
        扫描失败/目录不存在 → 0。"""
        try:
            d = os.path.dirname(cls._boot_path())
            best = 0
            for name in os.listdir(d):
                if not name.endswith(".wseq"):
                    continue
                try:
                    with open(os.path.join(d, name), encoding="utf-8") as f:
                        best = max(best, int((f.read() or "0").strip() or 0)
                                   // cls._BOOT_STRIDE)
                except Exception:
                    continue
            return best
        except Exception:
            return 0

    @staticmethod
    def _boot_path():
        return os.path.join(
            os.path.expanduser("~"), ".serialconsole_pro", "v4wseq", "BOOT")

    def _bump_hwm(self, w):
        """落账后推进本 epoch 桶的高水位（LRU：提到末尾）。"""
        with self.__class__._hwm_lock:
            key = self.epoch or ""
            cls = self.__class__
            if w > cls._hwm.get(key, 0):
                cls._hwm.pop(key, None)
                cls._hwm[key] = w

    def _reset(self, epoch, hydrate=None):
        self.epoch = epoch
        # 二十二次全审（结构）：feed 实例身份。客户端游标必须同时携带
        # 它——**身份匹配**取代「数值严格单调」。理由：22 轮审计证明
        # 「起点永远大于旧游标」在「持久化可丢 + 时钟可回拨 + 并发可撞号」
        # 下不可达（见文档 §5.9）。而身份匹配不依赖任何可失效状态：
        # 换了实例就是换了空间，客户端游标一律作废走快照。
        self.incarnation = uuid.uuid4().hex[:16]
        self.snap = P.new_snapshot(epoch)
        # F1：快照 toSeq 必须从注入起点起步（不能是 0）——客户端拿到的
        # toSeq 就是它下一次续传的游标，若发 0 会让旧游标「合法」落进新
        # 空间（同上文丢历史）。
        self.snap["seq"] = self._wseq_base
        self._row_id = 0
        self._log = []                 # [(wseq, [delta,...]), ...]
        self._seqs = []                # 与 _log 平行的 **wseq** 列表（bisect 游标用）
        # 投递序号（wire seq）与真实事件 seq 分离（a116 九次全审，根修）：
        #   * 真实 seq（信封里的 store seq）只用于**判重**：同一事件重复摄入
        #     （补放/live 双喂/重连重放）必须幂等丢弃；
        #   * wseq 是**投递序号**，单调递增、只增不减，客户端游标/快照 toSeq
        #     一律用它。迟到事件拿到一个**新的末尾 wseq**，天然落在任何游标
        #     之后 → frames_after 一定能投递。
        # 历史教训：曾让 snap["seq"] 同时兼任两者，迟到时靠「哨兵 +1」让快照
        # 前进——而 store 的 seq 是连续的，哨兵后的水位恰好等于下一笔真实
        # seq，该真实事件必然再被判「迟到」，此后每个事件都退化为整窗快照
        # （九次全审实测 16/17 轮全是快照）。分离后该循环不可能发生。
        # 跨实例单调（F1，a116 十次全审）：wseq **绝不能**每次从 1 重编号。
        # feed 会被重建（TTL 换空 feed、临时 feed 转正式、进程重启后
        # lifecycle restore 沿用同一 epoch），而客户端持久化的游标是旧实例
        # 的 wseq。若新实例从 1 起编，旧游标 3 在新空间里 map 到「第 3 个
        # 事件」→ resume_probe 返回 ok → 只发增量 → **旧游标之前的行永久
        # 缺失且永不回退快照**（审计实测丢 3/15 条）。
        # 解法：起点由调用方注入（主 feed 用账本水位 + 余量，子 feed 用毫秒
        # 时间戳），保证新实例的 wseq 严格大于任何旧实例发过的值。
        self._wseq = self._wseq_base    # 最后分配的投递序号（= snap["seq"]）
        self._seq_set = set()          # 已摄入的**真实** seq（判重）
        self._seq_fifo = []            # 真实 seq 的到达序（有界回收用）
        self._resnap_ver = 0           # 保留但恒为 0（分离后无需重对齐）
        self._late_lo = 0              # 保留字段（恒 0），见下方说明
        self._late_snap = 0
        # F1：空 log 时下界必须是**起点**而非 0——否则旧实例的游标（3）
        # 满足 `3 >= 0` 被判可续传，而新实例从 500 起编 → 3..499 的事件
        # 永远取不到（审计实测丢 3/15 条）。起点即「本实例已知的最早可
        # 投递位置」，语义与 _trim 后的 log[0][0] 一致。
        self._floor_seq = self._wseq_base   # log 内最老条目的 **wseq**
        # 字段 `_first_issued` 已随判据一并删除（二十一次全审）：撞等号
        # 风险由 `_claim_base` 的持久化启动序号结构性消除，不再需要此尺。
        # 帧文本缓存（多订阅者同 (fromSeq,toSeq) 只 json.dumps 一次——同帧
        # 广播；racy 单槽，最坏重复序列化，无害）。_trim 越窗丢弃时失效
        self._frm_cache = None         # ((frm, to), sse_text)
        self._snap_txt = None          # (seq, sse_text)
        self._pending_tools = {}       # tool_use id -> rowId（终态配对）
        self._pending_agents = {}      # Task tool_use id -> (sub行, tool行)
        self._exit_marker_row = None   # 最近 exit marker 行（interrupted 合并锚）
        self._turn_rows = {}           # turnId -> turn_header rowId
        self._hydrate = hydrate        # 冷启动重建回调（snapshot 空时调用）
        self._hydrated = False
        self._hyd_keys = set()         # hydration 已呈现行的内容指纹（去重）
        self._hyd_max_at = 0           # hydration 全部行的最大时刻（去重上界）
        self._held = False             # 后台子代理 hold（result 不提前收口）
        self._replay = False           # 水位补放阶段（历史重复行过滤）
        # a65：子 feed uuid 去重（设计 §5.2）——watcher 增量与 hydrate 全量
        # 并发喂同一文件时同一行双画；CLI jsonl 行 uuid 是稳定键（主 feed 无
        # 此问题：信封 seq 天然幂等）
        self._seen_uuid = set()
        if hydrate:
            hydrate(self)              # 重建路径直接填 snapshot（不发 delta）
        # reset 后让所有等待者重新对账（feed 重建=内容全变）
        with self._cv:
            self._ver += 1
            self._cv.notify_all()

    # ------------------------------------------------------------------
    # 行构造（reducer 内部）
    # ------------------------------------------------------------------
    def _row(self, turn, kind, at, at_seq, **fields):
        self._row_id += 1
        row = P.mk_row(self._row_id, turn or "", kind, at, at_seq, **fields)
        return P.d_row_appended(row), self._row_id

    def _upsert(self, row_id, **fields):
        """按 rowId 换整行（保留行原有字段——从当前快照行取）。"""
        for r in self.snap["rows"]:
            if r["rowId"] == row_id:
                nr = dict(r)
                nr.update(fields)
                return P.d_row_upserted(nr), nr
        return None, None

    # ------------------------------------------------------------------
    # ingest：信封事件 → deltas（主会话 reducer）
    # ------------------------------------------------------------------
    def ingest(self, env):
        t = env.get("type")
        # 字段合并视图：V3 事件的业务字段有两种布局——user_echo/renew/peer/
        # queue 族在**信封顶层**（session.py emit {"kind":"user_echo",
        # "text":...}），cli_stream 族在 data 里。只查 data 会全部取空
        # （实测 a17：用户消息行 text 全空=气泡空白根因）。合并：顶层非信封
        # 字段打底，data 覆盖（cli_stream 的 data 无顶层重名，安全）
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        _top = {k: v for k, v in env.items()
                if k not in ("type", "kind", "seq", "ts", "epoch",
                             "sid", "turn", "data")}
        if _top:
            _m = dict(_top)
            _m.update(data)
            data = _m
        seq = env.get("seq") or 0
        turn = env.get("turn") or ""
        ts = env.get("ts") or 0
        ds = []
        with self._lock:
            # 严重5（a116 全审）：判重必须在应用**之前**——重复摄入若先
            # apply 再丢弃，投影会二次应用（实测同一 env 喂两次：rows 两份
            # HELLO）。但**登记**必须在成功之后（F2，十次全审）：
            # `_commit` 里登记，异常时调用方回队重试仍能放行。
            if self._seen_seq(seq):
                return
            if t == "user_echo":
                self._exit_marker_row = None   # 新回合=合并锚失效
                if self._dup_hist("user_input", data.get("text"), ts):
                    return                # 补放与 hydration 重叠：不重画
                hd, _hr = self._ensure_header(turn, ts, seq)
                if hd:
                    ds.append(hd)     # 组头先于用户气泡（顺序即渲染序）
                d, _ = self._row(turn, "user_input", ts, seq,
                                 text=data.get("text") or "",
                                 files=data.get("files") or [],
                                 images=data.get("images") or 0,
                                 cmd=data.get("cmd") or "")
                ds.append(d)
            elif t == "cli_stream":
                ds = self._reduce_cli(data, turn, ts, seq)
            elif t == "turn_started":
                if turn and turn not in self._turn_rows:
                    d, rid = self._row(turn, "turn_header", ts, seq,
                                       state="running",
                                       model=data.get("model") or "",
                                       startedAt=ts)
                    ds.append(d)
                    self._turn_rows[turn] = rid
                ds.append(P.d_state({"busy": True, "curTurn": turn}))
            elif t == "turn_complete":
                rid = self._turn_rows.get(turn)
                if rid is None and turn:
                    hd, rid = self._ensure_header(turn, ts, seq)
                    if hd:
                        ds.append(hd)
                if rid:
                    d, _ = self._upsert(rid, state="success",
                                        endedAt=ts,
                                        activeMs=data.get("duration_ms"))
                    if d:
                        ds.append(d)
                self._held = False
                ds.append(P.d_state({"busy": False}))
            elif t == "turn_hold":
                # 后台子代理在飞：result 已到但回合未完（session 不发
                # turn_complete）——标记后 _reduce_cli 的 result 兜底不收口
                self._held = True
            elif t == "turn_error":
                rid = self._turn_rows.get(turn)
                if rid:
                    d, _ = self._upsert(rid, state="error", endedAt=ts,
                                        err=data.get("brief") or "")
                    if d:
                        ds.append(d)
                ds.append(P.d_state({"busy": False}))
                self._held = False    # 与 turn_complete 对称：hold 不跨回合残留
            # S3 修复（a116）：原首个 `elif t == "interrupted"` 已删除——
            # 它无条件新建 marker 行并把组头翻 cancelled，使下面 :327 的
            # 「与 exit 合并为一行」永远是死代码。实测 turn_complete(success)
            # 之后收到 exit+interrupted 时组头被错误翻成 cancelled，且
            # marker 双行（正是注释说要避免的孤儿组）。合并版统一收口。
            elif t == "subagent_started":
                # a112（用户实锤「出错的子代理刷新后复活成运行中」）：镜像
                # 不复活终态链——readmodel 的 2s Sync 按 mtime 新鲜度重发
                # running 镜像（刚死代理——上下文爆等——转写 mtime 还在
                # 新鲜窗内即被判跑），若镜像携带的 tid 已有终态 SUB 行
                # （error/success），即陈旧重发，整条丢弃。判 tid 不判
                # childTopic：续派 resume（合法复活）带**新包装 tid**，
                # 不命中终态行——放行
                _tid0 = data.get("tid") or ""
                if _tid0 and any(r.get("kind") == "subagent"
                                 and r.get("tid") == _tid0
                                 and r.get("status") not in (None, "", "running")
                                 for r in self.snap["rows"]):
                    return
                hd, _hr = self._ensure_header(turn, ts, seq)
                if hd:
                    ds.append(hd)
                agent = data.get("task_id") or data.get("aid") or ""
                _tid = data.get("tid") or ""
                _inp = data.get("input") or {}
                _desc = (data.get("desc") or _inp.get("description") or "")
                _prev = self._pending_agents.get(_tid) if _tid else None
                if _prev:
                    # a54/a65：readmodel 2s Sync 重发同 tid 镜像（aid 后到）——
                    # 只 upsert subagent 行（summary/childTopic 补绑），**不建
                    # tool_call 行**（a65 定案：转写里的 Task tool_use 才是
                    # 权威卡，镜像建行=同子代理双卡且镜像行永无终态）
                    srid = _prev[0]
                    _f = {"summary": _desc}
                    if agent:
                        _f["childTopic"] = "sub:" + agent
                    d, _ = self._upsert(srid, **_f)
                    if d:
                        ds.append(d)
                else:
                    d, rid = self._row(turn, "subagent", ts, seq,
                                       tid=_tid,
                                       agentType=data.get("agent_type") or data.get("type") or "Agent",
                                       status="running",
                                       summary=_desc,
                                       childTopic="sub:" + agent if agent else "")
                    ds.append(d)
                    # a65：不再镜像建 tool_call 行——权威卡=转写 Task tool_use
                    # （cli_stream 归约建行），镜像行是「永无终态的第二张卡」
                    # 实测根源。档案回写由前端 bridge 终态帧 childTopic 直取
                    if _tid:
                        self._pending_agents[_tid] = (rid, None)
            elif t == "subagent_result":
                tid = data.get("tid") or ""
                pair = self._pending_agents.pop(tid, None)
                ok = bool(data.get("ok"))
                # v4.0.3（用户实锤「已停止的子代理胶囊还显示运行中」）：
                # 停止 ≠ 失败。stopped 的终态要把 SUB 行从 running 翻成
                # success（画「已停止」徽章而非红叉）——原实现 ok=False
                # 会落 failed，用户看到的是出错。
                _stopped = bool(data.get("stopped"))
                _st = ("success" if ok or _stopped else "failed")
                _brief = (data.get("brief") or "").strip()
                if pair is None:
                    # v4.0.3 兜底：停止通知可能不带 tool-use-id（session 侧
                    # 已尽量反查 tid，但冷启动窗口内反查可能落空）——按
                    # **agentId（task_id/aid）** 找本 feed 里 running 的
                    # SUB 行，它就是同一个子代理。找不到就放弃（无行可翻）。
                    # **不能 return**：reducer 的 return 语义是「本条变更
                    # 生成完毕」而非「跳过剩余分支」——下面 tool 行回填与
                    # 其它副作用仍需执行。用 _rid_x 是否命中决定是否 upsert。
                    _aid_x = str(data.get("task_id") or data.get("aid") or "")
                    _rid_x = None
                    if _aid_x:
                        for _r in self.snap["rows"]:
                            if (_r.get("kind") != "subagent" or _r.get("status")
                                    not in (None, "", "running")):
                                continue
                            if (str(_r.get("childTopic") or "")
                                    .replace("sub:", "") == _aid_x):
                                _rid_x = _r.get("rowId")
                                break
                    if _rid_x is not None:
                        # brief 空时**不能**覆盖 summary——停止通知通常不带
                        # 摘要，写成空串会把行卡标题抹掉（实测派发后变空）。
                        _f = {"status": _st, "endedAt": ts}
                        if _stopped:
                            _f["stopped"] = True    # 前端据此画「已停止」
                        if _brief:
                            _f["summary"] = _brief
                        d, _ = self._upsert(_rid_x, **_f)
                        if d:
                            ds.append(d)
                if pair:
                    srid = pair[0]
                    _f2 = {"status": _st, "endedAt": ts}
                    if _stopped:
                        _f2["stopped"] = True
                    if _brief:
                        _f2["summary"] = _brief
                    d, _ = self._upsert(srid, **_f2)
                    if d:
                        ds.append(d)
                # a66R：真结论回填权威 tool 行——a67 实测修正：CLI 新版
                # task_notification.summary 本身就是投递元数据（"This agent's
                # report was delivered…"），真结论在 hand-back 注入消息正文
                # （下方 user 分支处理）。元数据 brief 不回填（还会误覆盖后台
                # Bash 行的真实输出——bg bash 完成也走 notification 镜像）
                if (_brief and tid and not hb_is_meta(_brief)):
                    _trid = next((r["rowId"] for r in self.snap["rows"]
                                  if r.get("kind") == "tool_call"
                                  and r.get("tid") == tid), None)
                    if _trid:
                        # a90：真终态带 status/endedAt——ack 被抑制后 tool 行
                        # 从派发起保持 running，此处是它的终态翻转点（回放/
                        # 重建按 status 定形态，缺 status=假运行）
                        d3, _ = self._upsert(_trid,
                                             status="success" if ok else "failed",
                                             output="✅ " + _brief[:2000],
                                             endedAt=ts)
                        if d3:
                            ds.append(d3)
            elif t == "peer":
                ds = self._reduce_peer(data, turn, ts, seq)
            elif t == "interrupted":
                # 中断与 exit 连发（杀进程中断=exit 先到 interrupted 后到）合并
                # 为一行：双行会在回放侧触发 turn_interrupted 编排两次建组
                #（store.js grpEnsure）——第二条凭空建空组定稿=「已工作 0 秒」
                # 孤儿组（用户实测）。V3 转写侧本就只补一条中断痕迹行
                text = data.get("text") or data.get("msg") or ""
                rid_ex = self._exit_marker_row
                if rid_ex:
                    d, _ = self._upsert(rid_ex, mkind="interrupted", text=text)
                else:
                    d, _ = self._row("", "marker", ts, seq,
                                     mkind="interrupted", text=text)
                if d:
                    ds.append(d)
                # S3 补充（a116）：组头只在本回合尚未定稿时才翻 cancelled——
                # 已完成（success/error）的组不得被后到的中断信号改写。
                rid = self._turn_rows.get(self.snap["state"].get("curTurn"))
                if rid:
                    cur = next((r for r in self.snap["rows"]
                                if r["rowId"] == rid), None)
                    if cur is None or cur.get("state") not in ("success", "error"):
                        d2, _ = self._upsert(rid, state="cancelled", endedAt=ts)
                        if d2:
                            ds.append(d2)
                ds.append(P.d_state({"busy": False}))
            elif t == "sysnote":
                # 系统提示不占位（用户拍板 a39：「系统提示 · 已注入…」气泡
                # 当时只是没改）——skind 标记 task-notification（后台代理完成
                # 通知有摘要信息量，保留），纯注入提示行前端不画
                text = data.get("text") or data.get("msg") or ""
                _sk = ("task-notification"
                       if ("<task-notification" in text or "任务通知" in text)
                       else "")
                d, _ = self._row("", "marker", ts, seq, mkind=t, text=text,
                                 skind=_sk)
                ds.append(d)
            elif t in ("renew", "audit", "exit", "model_switched"):
                text = data.get("text") or data.get("msg") or ""
                # a93S（用户定调「这个不显示」）：后台保活探活卡（[保活]/[限流]
                # 30/45/60 分钟催促）是监控噪音不进消息流——emit 与 audit log
                # 保留（V3 警示卡实时可见+审计存档），v4 投影不落行
                # （live/刷新/回放全干净）
                if t == "audit" and text.startswith(("[保活", "[限流")):
                    return
                d, rid = self._row("", "marker", ts, seq, mkind=t, text=text)
                ds.append(d)
                # 记录最近 exit marker 行（interrupted 合并锚；新 exit 覆盖）
                if t == "exit":
                    self._exit_marker_row = rid
            elif t == "ask":
                # 交互提问进 A 区（V3 形态=挂 dock 的 askRender 面板，非消息行）；
                # 前端 v4view paintState 消费。幂等：askRender 同 req_id 查重。
                ds.append(P.d_state({"ask": {
                    "req_id": data.get("req_id") or "",
                    "title": data.get("title") or "",
                    "questions": data.get("questions") or [],
                }}))
            elif t == "ask_done":
                ds.append(P.d_state({
                    "ask": None,
                    "ask_done": {"req_id": data.get("req_id") or "",
                                 "answer": data.get("answer")},
                }))
            elif t in ("input_admitted", "input_promoted", "input_discarded"):
                # queue 真源在 durable 排队账本；仅当事件携带全量 queue 时才
                # 更新 A 区（否则等路由订阅时冷填）
                if isinstance(data.get("queue"), list):
                    ds.append(P.d_state({"queue": data["queue"]}))
            if not ds:
                return
            P.apply_deltas(self.snap, ds)
            self._commit(seq, ds)          # F4：水位由 _commit 只增维护

    def _dup_hist(self, kind, text, at=0):
        # 补放期去重：该行是否已由 hydration 呈现。
        #
        # 单一方向边界（不是 ±5s 绝对值）：hydration 读的是「创建 feed 时刻
        # 已落盘的转写」，其最大行时刻 = _hyd_max_at。同一条事件的 jsonl 行
        # 与账本补放行的时刻同源，必然 at <= _hyd_max_at + 容差；而用户此后
        # 重发同文本的新消息 at 必然更大 → 不会被误杀（round-2 的 ±5s 双向
        # 窗口会误杀「5s 内原样重发」）。
        # 容差 2s：jsonl 的 ts 由 CLI 打、env ts 由 harness emit 时打，同一条
        # 事件两者可差数百毫秒。
        # 已知残留：同文本且在 hydration 末行 2s 内的新消息仍会被当作重复
        # （仅 feed 冷建的那一次补放窗内，窗口极窄）。
        if not self._replay or not self._hyd_keys:
            return False
        if (kind, (text or "")[:200]) not in self._hyd_keys:
            return False
        if at and self._hyd_max_at:
            return at <= self._hyd_max_at + 2000
        return True

    @staticmethod
    def _is_sub_mirror(o):
        """子代理镜像/注入行判据（对齐 sse.js 的既有分层口径）。

        红线：子代理正文/工具绝不允许进主投影。CLI 把子代理事件镜像到主
        会话 stdout（带 parent_tool_use_id），旧 handleEvent 靠这些字段分流
        到子窗格；v4 主 feed 若不过滤，子内容会直接流进主窗口。

        分层（与 sse.js:285/697 与 :30 一致——不做统一加宽，防误杀主链）：
        - assistant/user/result 等业务事件：parent_tool_use_id / isSidechain
          / isMeta（a65 补——设计 §5.2 列明，CLI 对 sidechain 元行打 isMeta，
          sse.js:1549 同款丢弃）
        - system 生命周期事件：另加 agent_id（嵌套派发的唯一标记）
        """
        if o.get("parent_tool_use_id") or o.get("isSidechain") or o.get("isMeta"):
            return True
        return o.get("type") == "system" and bool(o.get("agent_id"))

    def _ensure_header(self, turn, ts, seq, model=""):
        """组头懒建（turn_started 缺失兜底）：任何带 turn 的行到达时补建，
        否则组头永远不出现（「工作组头不出现」红线的构造性防线）。"""
        if not turn or turn in self._turn_rows:
            return None, None
        d, rid = self._row(turn, "turn_header", ts, seq,
                           state="running", model=model, startedAt=ts)
        self._turn_rows[turn] = rid
        return d, rid

    def _reduce_cli(self, data, turn, ts, seq):
        """CLI stream-json 事件 → deltas。"""
        ds = []
        if self._is_sub_mirror(data):
            return ds                     # 子代理镜像行：不进主投影（红线）
        typ = data.get("type")
        if typ == "assistant":
            m = data.get("message") or {}
            model = m.get("model") or ""
            hd, _hr = self._ensure_header(turn, ts, seq, model)
            if hd:
                ds.append(hd)
            for b in (m.get("content") or []):
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text" and (b.get("text") or "").strip():
                    d, _ = self._row(turn, "assistant_text", ts, seq,
                                     text=b["text"], model=model)
                    ds.append(d)
                elif bt == "thinking" and (b.get("thinking") or "").strip():
                    d, _ = self._row(turn, "reasoning", ts, seq,
                                     text=b["thinking"])
                    ds.append(d)
                elif bt == "tool_use":
                    name = b.get("name") or ""
                    d, rid = self._row(turn, "tool_call", ts, seq,
                                       tool=name, status="running",
                                       input=_in_obj(b.get("input") or {}),
                                       startedAt=ts,
                                       tid=b.get("id") or "")
                    ds.append(d)
                    if b.get("id"):
                        self._pending_tools[b["id"]] = rid
        elif typ == "user":
            m = data.get("message") or {}
            # a68：子代理结论回传（CLI 新版 hand-back）——注入消息含
            # [Subagent hand-back] 标记+from aid+报告全文。全文不进消息流
            #（V3 401 同款），提取正文回填对应子代理的 tool 行（卡摘要）+
            # subagent 行（summary）——「结论回传」的正道数据源
            _hb = None
            _c0 = m.get("content")
            if isinstance(_c0, str) and "[Subagent hand-back]" in _c0:
                _hb = _c0
            elif isinstance(_c0, list):
                for _b in _c0:
                    if (isinstance(_b, dict) and _b.get("type") == "text"
                            and "[Subagent hand-back]" in str(_b.get("text") or "")):
                        _hb = str(_b.get("text"))
                        break
            if _hb is not None:
                _am = HB_AID_RE.search(_hb)
                _aid = _am.group(1) if _am else ""
                _body = hb_report_body(_hb)
                _tid = next((r.get("tid") for r in self.snap["rows"]
                             if r.get("kind") == "subagent"
                             and r.get("childTopic") == "sub:" + _aid), "") if _aid else ""
                if _tid:
                    _trid = next((r["rowId"] for r in self.snap["rows"]
                                  if r.get("kind") == "tool_call"
                                  and r.get("tid") == _tid), None)
                    if _trid:
                        # a90：hand-back 真结论回填同带终态翻转（bg 代理 ack
                        # 被抑制后，这里是 tool 行的另一个终态来源）
                        d, _ = self._upsert(_trid, status="success",
                                            output="✅ " + _body[:4000],
                                            endedAt=ts)
                        if d:
                            ds.append(d)
                    _srid = next((r["rowId"] for r in self.snap["rows"]
                                  if r.get("kind") == "subagent"
                                  and r.get("childTopic") == "sub:" + _aid), None)
                    if _srid:
                        d, _ = self._upsert(_srid, summary=_body[:400],
                                            status="success", endedAt=ts)
                        if d:
                            ds.append(d)
                if not ds:
                    return ds
            for b in (m.get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    rid = self._pending_tools.pop(b.get("tool_use_id"), None)
                    if rid is None:
                        continue
                    err = bool(b.get("is_error"))
                    out = _txt(b.get("content"))[:8000]
                    _tr = next((r for r in self.snap["rows"]
                                if r["rowId"] == rid), None)
                    # a90 根修（用户实锤「切会话回来不同步/假完成」的源头）：
                    # run_in_background 的 Task/Agent 派发后 CLI 立即回一条
                    # tool_result（"agent launched successfully… for internal
                    # use…"）——它是「已派出」内部回执，不是任务结果。此处
                    # 曾无条件终结行（status=success），Agent 行在派发时刻就
                    # 定死：live 卡片定格「完成」打 dataset.final=过程文本同步
                    # 全停（_subLivePaint 见 final 早退），重建/切回吃快照同样
                    # 假完成。真终态=task_notification（subagent_result 镜像，
                    # 下方回填真摘要）与 hand-back（user 分支回填 ✅ 报告）。
                    # V3 同款认知：sse.js a.bg 守卫 / tools.js _hgIsBgLaunchAck
                    # P1-7 修复（a116）：ACK 判据不能依赖 run_in_background
                    # 字段——真实样本 194 个 Task/Agent tool_use 里 118 个
                    # **没有该字段**（CLI 版本差异），138 条 ACK 回执中 98 条
                    # 属这种形态 → 旧判据漏检 71%，Agent 行在派发时刻即定格
                    # 「完成」（正是 a90 声称修掉的假完成）。改按**回执文本
                    # 形态**判定：ACK 文案是 CLI 固定串，与字段无关。
                    _ack_out = _txt(b.get("content"))[:4000]
                    _is_ack_txt = is_bg_ack(_ack_out)
                    if (_tr is not None
                            and _tr.get("tool") in ("Task", "Agent")
                            and not err
                            and ((_tr.get("input") or {}).get("run_in_background")
                                 or _is_ack_txt)):
                        continue          # 已派出回执：保持 running，等真终态
                    # a110S（用户要求「sendmessage 的子代理格也要同步，不能
                    # 切回来直接显示完成」）：SendMessage 行卡的语义=**续派链**
                    # 而非该 tool 调用本身——送达回执（resumedAgentId…）只是
                    # 「已转交」，链在跑它就必须 running+同步。真终态=链的
                    # task_notification（tid=包装 SendMessage call id，
                    # subagent_result 回填分支按 tid 扫描精确命中本行）
                    if (_tr is not None
                            and _tr.get("tool") == "SendMessage"
                            and not err):
                        continue
                    # a48（用户定调「回答形态要 a42 效果」）：ask_user 的
                    # 回答在后端人类可读化——原始 JSON {"问题":"答案"} →
                    # 「📝 回答：问题 → 答案；…」。数据在后端整合（红线），
                    # 前端 live/回放/体全场景直接吃到成品文本
                    _tn = _tr.get("tool") if _tr else ""
                    if _tn == "mcp__harness__ask_user" and not err:
                        try:
                            _oj = json.loads(out)
                            if isinstance(_oj, dict):
                                out = "；".join(
                                    "%s → %s" % (k, v)
                                    for k, v in _oj.items()) or out
                        except Exception:
                            pass
                        out = "📝 回答：" + out
                    d, _ = self._upsert(
                        rid, status="error" if err else "success",
                        output=out,
                        endedAt=ts)
                    if d:
                        ds.append(d)
        elif typ == "system":
            # a52：压缩状态事件（{"type":"system","subtype":"status",
            # "status":"compacting"|"requesting"}）进 A 区 state——v4 归一后
            # per-sid 投影天然隔离（V3 全局 _HG.compacting 串台根因消除）；
            # 前端 bridge 消费置 _HG.compacting/compactT0 并驱动压缩线
            if data.get("subtype") == "status":
                _st = data.get("status") or ""
                if _st == "compacting" and not self.snap["state"].get("compacting"):
                    self.snap["state"]["compacting"] = True
                    self.snap["state"]["compactT0"] = ts or int(ts) or 0
                    ds.append(P.d_state({"compacting": True,
                                         "compactT0": ts or 0}))
                elif _st != "compacting" and self.snap["state"].get("compacting"):
                    self.snap["state"]["compacting"] = False
                    ds.append(P.d_state({"compacting": False}))
            m = data.get("message") or {}
            md = m.get("model") or ""
            if md:
                ds.append(P.d_state({"model": md}))
        elif typ == "result":
            # 兜底收口：turn_started/turn_complete 缺失（CLI 自发回合、旧版
            # CLI）时也要有组头终态——否则前端组永远停在「工作中」。hold 期
            # （后台子代理在飞）session 不发 turn_complete，结果帧照常到达，
            # 此时**不**收口（避免组头提前 success 而 busy 仍 True）。
            if getattr(self, "_held", False):
                return ds
            rid = self._turn_rows.get(turn) if turn else None
            if rid:
                d, _ = self._upsert(rid, state="error" if data.get("is_error")
                                    else "success", endedAt=ts,
                                    activeMs=data.get("duration_ms"))
                if d:
                    ds.append(d)
        return ds

    def _reduce_peer(self, data, turn, ts, seq):
        """peer 族（session.py emit {kind:'peer', name, text, to}——name 含
        「识图」=识图会话回传代播）。字段按后端真身取：旧 title/brief 从未
        匹配过（回传正文全丢）；识图发起不在此处——走 cli_stream 的识图
        tool_use（V3 同源：sse.js 双通道工具名分支建卡起表）。

        a69：hand-back 回传（子代理结论，session.py 跨会话捕获 emit）——
        text 含 [Subagent hand-back] 标记。提取 from aid+报告正文，回填对应
        子代理的 tool 行（卡摘要 ✅+正文）+subagent 行（summary），**不建
        peer_notify 行**（a17 非识图回传不进消息流；此前结论在此被整条丢掉
        =用户实测「没有任何结论回传」）。"""
        ds = []
        _text = str(data.get("text") or "")
        if "[Subagent hand-back]" in _text:
            import re as _re
            _am = (HB_AID_RE.search(_text)
                   or _re.search(r'from-name="([0-9a-zA-Z_-]{8,64})"', _text))
            # a72：session.py 专用事件带 aid 字段（最可靠），正文 from 次之
            _aid = (str(data.get("aid") or "")
                    or (_am.group(1) if _am else "")
                    or str(data.get("name") or ""))
            _body = hb_report_body(_text)
            # a74：tid 精确匹配优先（session.py a72 事件自带 tool_use_id）——
            # childTopic 依赖 aid 及时分发（未到手时行 childTopic 空=永不命中，
            # 实测元数据摘要残留根因）；childTopic 匹配保留为兜底
            _tid = (str(data.get("tid") or "")
                    or next((r.get("tid") for r in self.snap["rows"]
                             if r.get("kind") == "subagent"
                             and (r.get("childTopic") or "") == "sub:" + _aid), ""))
            if _tid:
                _trid = next((r["rowId"] for r in self.snap["rows"]
                              if r.get("kind") == "tool_call"
                              and r.get("tid") == _tid), None)
                if _trid:
                    # P1-6 修复（a116）：真结论到达即该链终态——原实现只写
                    # output 不翻 status/endedAt，而 a111 起 SendMessage 的
                    # tool_result 回执被一律判为非终态，真终态只认 notification
                    # 镜像（tid=包装 call id）。真实数据：125 个 SendMessage
                    # tool_use 里 69 个（55%）无同 tid notification → 那些行
                    # 永久 running（秒表永跑、轮盘永转），而结论明明已回填。
                    # 与 _reduce_cli 的 a90 回调同口径：终态翻转 + endedAt。
                    d, _ = self._upsert(_trid, status="success",
                                        endedAt=ts,
                                        output="✅ " + _body[:4000])
                    if d:
                        ds.append(d)
                _srid = next((r["rowId"] for r in self.snap["rows"]
                              if r.get("kind") == "subagent"
                              and (r.get("childTopic") or "") == "sub:" + _aid), None)
                if _srid:
                    d, _ = self._upsert(_srid, summary=_body[:400],
                                        status="success", endedAt=ts)
                    if d:
                        ds.append(d)
            return ds
        d, _ = self._row("", "peer_notify", ts, seq,
                         name=data.get("name") or "其他会话",
                         text=_text[:8000],
                         to=data.get("to") or "")
        ds.append(d)
        return ds

    # ------------------------------------------------------------------
    # 子代理 jsonl 行归约（watcher 增量与 hydrate 共用）
    # ------------------------------------------------------------------
    def feed_jsonl_line(self, obj, hydrate=False):
        """CLI 转写 jsonl 单行（dict）→ deltas 入子投影。返回是否消费。"""
        if not isinstance(obj, dict):
            return False
        # a65：uuid 去重——hydrate 全量与 watcher 增量重叠窗口的同行双喂，
        # 同 uuid no-op（行级幂等由 _log seq 承担，这里是入馈闸）
        _u = obj.get("uuid")
        if isinstance(_u, str) and _u:
            if _u in self._seen_uuid:
                return False
            self._seen_uuid.add(_u)
            if len(self._seen_uuid) > 4096:
                self._seen_uuid = set(list(self._seen_uuid)[-4096:])
        ds = []
        # F4 配套（a116）：seq 必须在锁内分配——锁外 +1 会让并发调用撞号，
        # 而 _commit 对重复 seq 幂等丢弃（会静默吞掉一条真实事件）。
        # 这里先占位，进锁后立即重算（uuid 去重在锁外已完成）。
        seq = 0
        # a65：行时刻优先取行自身 timestamp（ISO/数字两形态）——喂入时刻
        # 是 hydrate/扫描的时钟（全文件同毫秒），据此算的轮时长恒「0 秒」；
        # jsonl 的 timestamp 才是事件真实时刻（V3 回放同源）。缺省回落 now
        ts = 0
        try:
            import time as _t
            ts = int(_t.time() * 1000)
            _tsv = obj.get("timestamp")
            if isinstance(_tsv, str) and _tsv.strip():
                import datetime
                ts = int(datetime.datetime.fromisoformat(
                    _tsv.replace("Z", "+00:00")).timestamp() * 1000)
            elif isinstance(_tsv, (int, float)) and _tsv > 0:
                ts = int(_tsv) if _tsv > 1e12 else int(_tsv * 1000)
        except Exception:
            pass
        typ = obj.get("type")
        with self._lock:
            # F4：锁内判重（真实 seq 判重与投递序号分离；jsonl 行 seq 恒为
            # 0 → 恒放行，重复喂由上面的 uuid 去重闸住）。
            # F2（十次全审）：登记推迟到 `_commit` 成功后。
            if self._seen_seq(seq):
                return False
            if typ == "result":
                self.snap["state"]["done"] = True
                self.snap["state"]["_doneAt"] = ts
                self.snap["state"]["final"] = (obj.get("result") or "")[:8000]
                self.snap["state"]["err"] = bool(obj.get("is_error"))
                ds.append(P.d_state({"done": True,
                                     "final": self.snap["state"]["final"],
                                     "err": self.snap["state"]["err"]}))
            elif typ in ("assistant", "user"):
                m = obj.get("message") or {}
                content = m.get("content")
                blocks = content if isinstance(content, list) else []
                # P2 修复（a116）：代理**重新在活动**时必须复位 done/final
                # ——续派（SendMessage resume）后 feed 实例按 (sid,agent)
                # 缓存复用，旧实现的 done 只置 True 不复位，于是续派后的
                # 任何重建都会立刻定稿新轮头（「已工作 0s」）且后续行落进
                # 已定稿轮。
                #
                # 续派的新一轮起点：user 行、**含文本块**、且 ts 不早于定稿
                # 时刻。MINOR-6（a116 三次全审）：原用「无 tool_result 块」
                # 判定，text+tool_result 混合块会漏（判据盲区）；改按「含
                # 文本」正向判。MINOR-7：同毫秒续派用 >= 而非 >。
                _prev_done_at = int(self.snap["state"].get("_doneAt") or 0)
                _is_new_round = False
                if typ == "user" and self.snap["state"].get("done") \
                        and ts >= _prev_done_at:
                    _is_new_round = bool(_txt(content).strip())
                if _is_new_round:
                    self.snap["state"]["done"] = False
                    self.snap["state"]["final"] = ""
                    self.snap["state"]["err"] = False
                    self.snap["state"].pop("_doneAt", None)
                    ds.append(P.d_state({"done": False, "final": "",
                                         "err": False}))
                if typ == "assistant":
                    model = m.get("model") or ""
                    for b in blocks:
                        if not isinstance(b, dict):
                            continue
                        bt = b.get("type")
                        if bt == "text" and (b.get("text") or "").strip():
                            d, _ = self._row("s", "assistant_text", ts, seq,
                                             text=b["text"][:2000], model=model)
                            ds.append(d)
                        elif bt == "thinking" and (b.get("thinking") or "").strip():
                            # a93R：model 随行——每条 assistant 消息都带
                            # message.model，只挂 text 行的话「零正文纯思考+
                            # 工具」的代理（审计类常态）头部模型槽永远空
                            d, _ = self._row("s", "reasoning", ts, seq,
                                             text=b["thinking"][:2000],
                                             model=model)
                            ds.append(d)
                        elif bt == "tool_use":
                            if b.get("name") == "SubagentHandback":
                                # 结论单一真源：只进 state.final（不落行流），
                                # 否则子 pane 时间线与结论区会各画一份（红线）
                                rep = ""
                                for v in (b.get("input") or {}).values():
                                    if isinstance(v, str) and len(v) > len(rep):
                                        rep = v
                                if rep.strip():
                                    self.snap["state"]["final"] = rep[:8000]
                                    self.snap["state"]["_doneAt"] = ts
                                    ds.append(P.d_state({"final": rep[:8000],
                                                         "done": True}))
                                    continue
                            d, rid = self._row("s", "tool_call", ts, seq,
                                               tool=b.get("name") or "",
                                               status="running",
                                               tid=b.get("id") or "",
                                               # a70（用户实锤「bash 看不到
                                               # 执行命令/与主窗不一致」）：
                                               # input 随行——卡头 hint
                                               # （command/file_path）/diff
                                               # 改动体/查阅聚组判定全靠它，
                                               # 与主投影 tool_use 同构
                                               # （_in_obj 截断防爆同款）
                                               input=_in_obj(b.get("input") or {}))
                            ds.append(d)
                            if b.get("id"):
                                self._pending_tools[b["id"]] = rid
                else:
                    t = _txt(content).strip()
                    # a78：[handback-send-enforce] 是 CLI 的强制投递指令（agent
                    # 报告写成正文没调 SubagentHandback 时注入）——机器噪音，
                    # 不进行流（否则 pane 多一轮+结论双份）
                    if t and not t.startswith("<") \
                            and not t.startswith("[handback-send-enforce]"):
                        # a117（用户实锤「第九轮对抗复审：上一轮结论被当
                        # 本轮结论，本轮还在跑却显示已工作」）：轮界复位——
                        # 上一轮 result/handback 已置 state.done/final，续派
                        # 新轮的 user 行到达=新轮开始，状态必须复位。曾不
                        # 复位：快照/看门狗重订阅携陈旧 done+旧 final 回放
                        # → 前端 _subFinish 把进行中的新轮定稿+旧结论顶上
                        # （并经 a96 传播把主窗档案也翻成假完成）
                        if self.snap["state"].get("done"):
                            self.snap["state"]["done"] = False
                            self.snap["state"]["final"] = ""
                            self.snap["state"]["err"] = False
                            ds.append(P.d_state({"done": False, "final": "",
                                                 "err": False}))
                        d, _ = self._row("s", "user_input", ts, seq, text=t[:1200])
                        ds.append(d)
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            rid = self._pending_tools.pop(
                                b.get("tool_use_id"), None)
                            if rid is None:
                                continue
                            err = bool(b.get("is_error"))
                            d, _ = self._upsert(
                                rid, status="error" if err else "success",
                                output=_txt(b.get("content"))[:8000],
                                endedAt=ts)
                            if d:
                                ds.append(d)
            if not ds:
                return False
            P.apply_deltas(self.snap, ds)
            self._commit(seq, ds)          # F4：水位由 _commit 只增维护
            return True

    def hydrate_jsonl(self, path):
        """从子代理转写文件全量重建（子投影冷启动）。
        性能批：分片水合——每 512 行让行 2ms，长转写（数 MB）不再把 worker
        GIL 独占秒级（期间其他 feed 的 SSE/ingest 全卡）。正确性不变：
        逐行顺序喂，只是插入喘气点。"""
        try:
            n = 0
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        o = json.loads(raw)
                    except Exception:
                        continue
                    self.feed_jsonl_line(o, hydrate=True)
                    n += 1
                    if n % 512 == 0:
                        time.sleep(0.002)
            self._hydrated = True
            return True
        except OSError:
            return False
        except Exception:
            # P2-5 修复（a116）：分片水合中途异常会留下半成品 feed，而
            # v4_sub_feed 只判「rows 非空就缓存」→ 半成品被永久固化。
            # 显式标记未水合 + 清空，让调用方丢弃重来。
            log.exception("hydrate_jsonl 中途失败 path=%s", path)
            self._hydrated = False
            with self._lock:
                self.snap["rows"] = []
                self.snap["total"] = 0
                # S2（a116 十五次全审）：uuid 去重集也必须清空——它在
                # feed_jsonl_line 里**先于落账**登记（:838-842），失败重试
                # 时前半段行会被判「已见过」整段跳过 → 5 行只回填 2 行，
                # 且返回 True/_hydrated=True → 半成品 feed 被永久缓存
                # （子代理窗格永久残缺，比不修更隐蔽）。
                self._seen_uuid = set()
            return False

    # ------------------------------------------------------------------
    # 订阅帧（拉模式；SSE 生成器事件驱动——wait_frames 等新帧，不再轮询）
    # ------------------------------------------------------------------
    def _commit(self, seq, ds):
        """统一落账：分配**投递序号 wseq** 并追加，成功后才登记真实 seq
        判重（a116 九/十次全审）。

        关键不变量：
          ① `_seqs` 是 wseq 的**严格递增**序列（追加即有序，不再 bisect 插入）
             → 迟到事件追加到末尾，任何游标都能取到它；
          ② `snap["seq"]` == 最后一个 wseq，只增不减，只作为客户端游标；
          ③ 真实 seq 只进判重集，且**登记点在成功之后**（F2）：原实现
             在 apply 之前登记，一旦 `apply_deltas`/reducer 抛瞬态异常、
             调用方回队重试（v4hub MAJOR-12 机制）就会被判重拒掉，
             该事件永久丢失。现在失败即不登记，重试可正常放行。
        """
        self._wseq += 1
        w = self._wseq
        self._log.append((w, ds))
        self._seqs.append(w)
        self.snap["seq"] = w
        self._bump_hwm(w)          # F1-R：推进进程级高水位（跨实例单调）
        # 跨**进程**持久化：把 wseq 高水位写回会话账本（随 meta 落盘），
        # 下一代的起点据此严格递增。仅主 feed 有 log_store（子 feed 为 None，
        # 其跨重建单调由类级 HWM 承担）。
        _st = getattr(self, "log_store", None)
        if _st is not None and w > getattr(_st, "wseq_hwm", 0):
            try:
                _st.wseq_hwm = w
            except Exception:
                log.exception("v4 wseq_hwm 回写失败")
        # F2（十次全审）：登记紧跟 append——此刻事件已确定进入 log/游标，
        # 即便后续 _trim/notify 抛错，投影与 log 也已一致，重试若再应用
        # 会二次画行，所以必须已登记。反过来（登记在 append 之前）会让
        # apply 阶段的瞬态异常把事件永久吃掉——两害相权取此。
        self._remember_seq(seq)
        try:
            self._trim()
        except Exception:
            log.exception("v4 _trim 失败（不影响本次落账）seq=%s", seq)
        with self._cv:
            self._ver += 1
            self._cv.notify_all()
        return True

    def _seen_seq(self, seq):
        """真实 seq 是否已成功摄入。调用方持锁。"""
        return bool(seq) and seq in self._seq_set

    def _remember_seq(self, seq):
        """登记真实 seq（**仅在成功落账后**调用）。调用方持锁。
        有界回收：只保留最近 8192 个真实 seq 的判重能力（内存有界）；
        更老的重复摄入概率极低（账本 retention=2000 < 8192，实际重放
        不会触发），且重复后果是「多画一行」而非丢数据。"""
        if not seq or seq in self._seq_set:
            return
        self._seq_set.add(seq)
        self._seq_fifo.append(seq)
        if len(self._seq_fifo) > 8192:
            _drop = len(self._seq_fifo) - 8192
            for _s in self._seq_fifo[:_drop]:
                self._seq_set.discard(_s)
            del self._seq_fifo[:_drop]

    def frame_version(self):
        """当前帧版本号（wait_frames 的配套锚点）。"""
        with self._cv:
            return self._ver

    def wait_frames(self, ver, timeout):
        """阻塞等 ver 之后的新帧（超时返回当时的版本号）。SSE 生成器的
        事件驱动等待口：空闲期线程挂条件变量上零 CPU，新帧落账即醒。"""
        with self._cv:
            if self._ver != ver:
                return self._ver
            self._cv.wait(timeout)
            return self._ver

    def _trim(self):
        """裁剪保留窗并**每次**同步 `_floor_seq`。

        F1-R 复发修（a116 十三次全审，致命）：原实现把 floor 更新写在
        `if len(self._log) > LOG_RETAIN` **块内**——log 非空但未满窗时
        floor 恒停在 `_wseq_base`，落后于 `_log[0][0]`。于是「旧游标 ==
        注入起点」在**新实例累计 < 600 事件**这个最常见窗口内被 `>=`
        放行 → 整段历史当增量重放 → 前端 rowId 撞号、【静默丢行】
        （审计实测 10 行被吞）。floor 必须无条件反映「本实例已知的最早
        可投递位置」：有 log 就是首条 wseq，无 log 就是注入起点。
        """
        if len(self._log) > LOG_RETAIN:
            drop = len(self._log) - LOG_RETAIN
            del self._log[:drop]
            del self._seqs[:drop]
            # a116 九次全审：`_log/_seqs` 现在装的是**投递序号 wseq**，
            # 与判重用的真实 seq 集合完全无关——这里**不得**再重建
            # `_seq_set`（旧实现同步重建导致越窗真实 seq 失去判重能力，
            # 同一事件二次投递会多画一行）。
            self._frm_cache = None   # 缓存帧的 from 已越窗：失效防引用已删 log
        # 无条件同步（不能放在上面的 if 里，见 docstring）
        self._floor_seq = (self._log[0][0] if self._log
                           else self._wseq_base)

    def frames_after(self, after_seq):
        """(after_seq, last] 合并帧（**投递序号**区间）。越窗/落后 → None
        （调用方发 snapshot）。epoch 校验由路由层做。
        性能批：bisect 游标定位起点（原线性全扫 O(N)）。
        a116 九次全审：`_seqs` 严格递增且迟到事件追加在末尾，所以迟到
        天然落在任何游标之后、常规增量路径必然取到——不再需要补投/重对齐。
        注意：安静 feed（无新帧）也返回 None——「无新帧」与「不可续传」的
        区分用 can_resume（a92）。"""
        with self._lock:
            if not self._in_window(after_seq):
                return None
            i = bisect.bisect_right(self._seqs, after_seq)
            ds = []
            for _w, dl in self._log[i:]:
                ds.extend(dl)
            if not ds:
                return None
            return P.coalesce(ds), self.snap["seq"]

    def _in_window(self, seq):
        """续传游标是否可**完整**续传。调用方持锁。

        两个条件必须同时成立：

        ① `seq >= _wseq_base`——不得低于本实例的空间起点。
        ② 有 log 且 `seq >= _floor_seq - 1`——`_trim` 只保留最近 600 条，
           floor 之前的增量**已经不存在**。若放行 `floor` 以下的游标，
           `frames_after` 只会返回 `(floor, last]` 这一截，客户端缺掉的
           中间段**永远不会补**（实测 700 条后 `frames_after(5)` 返回
           to=700 看着正常，实际漏掉 5..100）。允许 `floor - 1`：它表示
           「还没消费 floor 那条」，增量 `(floor-1, last]` 里 floor 本身
           仍在 log 中，完整。空 log 时无此约束（没有任何内容会漏）。

        关于 `seq == _wseq_base`（S1，十五次全审）：这是**合法**游标，不
        能不拒。快照 ack 下发的 `toSeq` 就是 `snap["seq"]`，空 feed 时
        正是 `base`；客户端拿着它回来续传必须被放行，否则「拿快照后
        断开、期间来一条事件」的每次重连都要重新整窗快照 + 前端全量
        重渲（a92/MAJOR-10 回归，审计实测 `can_resume(102)=False`）。
        「旧实例游标恰好等于新 base」这个风险**只能**由 `_claim_base`
        保证起点严格大于旧游标来消除——那是唯一有信息量的地方。
        """
        if seq < self._wseq_base or seq > self.snap["seq"] or seq < 0:
            return False
        # 十七次全审（一般级）：撞等号的结构性防线。`base` 是「空间起点」，
        # 上一代旧游标可能恰好等于它（无条件 max 兜底时 `hint` 取到上代
        # `last_seq` ⇒ `base = hint + 2` 可能 == 旧游标）。仅靠 base 判定
        # 会放行 → 旧游标落进新空间 → 静默丢行。用「本代首条」作尺：
        # 本代已有内容时，任何小于首条的游标都不可能完整续传。
        # 空 feed 不受限——快照 ack 的 toSeq 恰是 base，必须放行（S1）。
        # 本代首条判据：凡小于本代首条的游标，都缺了本代已发放的内容，
        # 不能算「完整续传」。`seq == 0` 的例外在此**不起作用**（`0 <
        # _wseq_base` 会先被上面的下界判据拒掉）——保留它只是为了让
        # 判据在「base 恰为 0」的构造型场景里语义自洽；生产路径上
        # routes 层 `base_seq > 0` 门已保证游标 0 不进 resume_probe。
        # `_first_issued` 判据已**删除**（二十一次全审）：它防的是「旧游标
        # 恰好等于本代 base」，而该风险已被 `_claim_base` 的**持久化启动
        # 序号**从结构上消除——boot 每次进程启动 +1，base 至少跳
        # `_BOOT_STRIDE`（10 亿），旧游标不可能与新 base 同值。
        # 保留它反而制造 S1 回归：快照 ack 下发的 toSeq 就是 base，客户端
        # 持它重连、期间恰来 1 条事件时会被判越窗 → 每次整窗快照 + 前端
        # 全量重渲（审计实测 rep15）。
        if self._log and seq < self._floor_seq - 1:
            return False
        return True

    def can_resume(self, base_seq):
        """base_seq（客户端游标 = 投递序号）是否可续传。a92：与
        frames_after 的 None 二义性解耦——安静 feed（无新帧但水位在窗内）
        应 resume 空转，不该整窗 snapshot。

        严格 `>` 而非 `>=`（F1-R，a116 十一次全审）：floor 是「本实例已知的
        最早可投递位置」。游标**等于** floor 意味着客户端已消费到 floor
        这个位置，而 floor 之前的内容它未必有——feed 换代（重建/重启/TTL）
        后旧游标恰好落在新 floor 上时，`>=` 会放行 → 只发增量 → 旧游标
        之前的行永久缺失且（同 epoch）永不回退快照（审计实测丢 E1..E4、
        重复 E500..E503）。用 `>` 让这种边界一律走整窗快照。"""
        with self._lock:
            return self._in_window(base_seq)

    def poll(self, after_seq):
        """原子取帧（一般-1 保留）。返回 `frame`，与 `frames_after` 同语义
        （None = 无增量或越窗）。a116 九次全审根修后迟到可正常投递，
        不再需要 `resnap_ver` 那一层，签名相应简化。"""
        with self._lock:
            if not self._in_window(after_seq):
                return None
            i = bisect.bisect_right(self._seqs, after_seq)
            ds = []
            for _w, dl in self._log[i:]:
                ds.extend(dl)
            if not ds:
                return None
            return P.coalesce(ds), self.snap["seq"]

    def resume_probe(self, base_seq):
        """起始续传裁决的原子版（can_resume + frames_after）。
        返回 `(ok, frame, last)`：
        - `ok=False` → 调用方发整窗 snapshot；
        - `ok=True, frame=None` → 可续传但无增量（安静 feed，只 ack）；
        - `ok=True, frame=(deltas, to)` → 有增量。"""
        with self._lock:
            if not self._in_window(base_seq):
                return False, None, 0
            i = bisect.bisect_right(self._seqs, base_seq)
            ds = []
            for _w, dl in self._log[i:]:
                ds.extend(dl)
            last = self.snap["seq"]
            if not ds:
                return True, None, last
            return True, (P.coalesce(ds), last), last

    def snapshot_wire(self, tail_turns=21, tail=0):
        with self._lock:
            # a41c（用户定调「放大不是办法」）：回合窗是唯一裁剪——行数闸
            # 删除（TAIL_ROWS 退役）。投影「行」有天然上界（一轮=思考段+工具
            # 调用+正文，工具输出截断在字段级非行级），不存在单轮爆行需兜的
            # 场景；行数闸与回合闸并存必打架（a41 实锤 21 回合恰卡 400 行被
            # 二次裁回 10 轮，a41b 放大只是把打架阈值后挪）。21=V3 窗 20 轮+1
            #（多 1 轮做前端 start>0 归档条判定锚）
            # a119P（用户实测「打开子代理卡顿」）：tail 出参——子 feed 大子
            # 会话（审计代理几千行）21 回合窗仍全量下发，前端渲染完又裁回
            # 220 行＝白干。子 topic 由 routes 传 tail=220（与前端时间线上限
            # _subTlCap 同值），主流不传维持回合窗唯一裁剪
            _w = P.wire_snapshot(self.snap, tail_turns=tail_turns, tail=tail)
            return _w

    @property
    def last_seq(self):
        with self._lock:
            return self.snap["seq"]
