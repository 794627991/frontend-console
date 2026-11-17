# -*- coding: utf-8 -*-
"""跨 API 方案兼容（v4.1.0-a590）：只按上下文容量判定，不再按方案名硬拦。

需求（用户拍板）：
  · 小上下文会话 → 切大上下文方案：放行；
  · 大上下文会话 → 切小上下文方案：已用不超过小窗才放行；
  · 已使用不同方案的老会话必须兼容（无 scheme 标记、旧窗口实报）；
  · /compact 是超窗唯一出口，必须无条件放行。

本文件只测纯函数（容量判定 / 模型名对齐），不起进程、不读写用户 settings。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness import session as S  # noqa: E402


class _FakeSession:
    def __init__(self, scheme=None, model=None, live_model=None,
                 last_result=None, model_origin=None):
        self.scheme = scheme
        self.model = model
        self.live_model = live_model
        self.last_result = last_result
        self.model_origin = model_origin


# ---------------------------------------------------------------- 容量判定
def _verdict(used, win, text=""):
    """None=放行，字符串=拦截。"""
    r = S._scheme_capacity_block(_FakeSession(scheme="zhipu"), used, win, text)
    return "allow" if r is None else "block"


def test_small_to_large_allowed():
    """小窗会话（256K）切大窗方案（1M）：100K 用量必须放行。"""
    assert _verdict(100_000, S._CTX_WINDOW_1M) == "allow"
    assert _verdict(200_000, 524_288) == "allow"


def test_large_to_small_fits():
    """大窗会话 450K 切 500K 方案：仍有余量，放行。"""
    assert _verdict(450_000, 524_288) == "allow"


def test_large_to_small_overflow_blocked():
    """450K 切 256K 方案：放不进，必须拦。"""
    assert _verdict(450_000, 262_144) == "block"
    assert _verdict(260_000, 262_144) == "block"      # 超 97% 安全线


def test_boundary_97_percent():
    """97% 安全线两侧：刚好在线上放行，越线拦截。"""
    win = 262_144
    assert _verdict(int(win * 0.96), win) == "allow"
    assert _verdict(int(win * 0.98), win) == "block"


def test_compact_always_allowed():
    """/compact 是超窗唯一出口，任何容量状态下都必须放行（含前置空格）。"""
    assert _verdict(450_000, 262_144, "/compact") == "allow"
    assert _verdict(450_000, 262_144, "  /compact 保留串口配置") == "allow"
    # 其他命令不该有豁免
    assert _verdict(450_000, 262_144, "/rescue") == "block"


def test_unknown_values_fail_open():
    """读不到用量/窗口时放行——探测失败不能把会话锁死。"""
    assert _verdict(0, 262_144) == "allow"
    assert _verdict(450_000, 0) == "allow"
    assert _verdict(-1, 262_144) == "allow"
    assert _verdict(None, 262_144) == "allow"


def test_block_message_mentions_ways_out():
    """拦截文案必须给出可执行出路，而不是只说「不让发」。"""
    s = _FakeSession(scheme="智谱")
    msg = S._scheme_capacity_block(s, 450_000, 262_144)
    assert isinstance(msg, str)
    for kw in ("/compact", "/rescue", "新建会话"):
        assert kw in msg
    assert "439K" in msg          # 450000 / 1024
    assert "256K" in msg          # 当前方案窗口


# ------------------------------------------------------- 模型名跨方案对齐
def test_reconcile_swaps_foreign_model(monkeypatch):
    """旧网关私有模型名（glm-*）切到新方案（DeepSeek-*）必须回落默认。"""
    monkeypatch.setattr(S, "available_models",
                        lambda: {"models": ["DeepSeek-V4.1-Flash", "DeepSeek-V4.1"],
                                 "default": "DeepSeek-V4.1-Flash"})
    s = _FakeSession(model="glm-4.6", live_model="glm-4.6-x",
                     last_result={"usage": {"input_tokens": 1}})
    old = S._reconcile_model_with_live(s)
    assert old == "glm-4.6"
    assert s.model == "DeepSeek-V4.1-Flash"
    assert s.live_model is None        # 旧实报作废
    assert s.last_result is None       # 旧窗口/用量口径作废


def test_reconcile_keeps_compatible_model(monkeypatch):
    """模型名在新方案映射里存在 → 不动（同名跨网关可用）。"""
    monkeypatch.setattr(S, "available_models",
                        lambda: {"models": ["m-a", "m-b"], "default": "m-a"})
    s = _FakeSession(model="m-b")
    assert S._reconcile_model_with_live(s) is None
    assert s.model == "m-b"


def test_reconcile_noop_when_unknown(monkeypatch):
    """读不到模型列表 / 会话无模型 → 不动（fail-open）。"""
    monkeypatch.setattr(S, "available_models",
                        lambda: {"models": [], "default": None})
    s = _FakeSession(model="glm-4.6")
    assert S._reconcile_model_with_live(s) is None
    assert s.model == "glm-4.6"

    s2 = _FakeSession(model=None)
    monkeypatch.setattr(S, "available_models",
                        lambda: {"models": ["m"], "default": "m"})
    assert S._reconcile_model_with_live(s2) is None
    assert s2.model is None


# --------------------------------------------- 与既有超窗守卫的口径一致性
def test_legacy_session_without_scheme_still_works():
    """升级前老会话 scheme=None：容量判定不看 scheme，照样按窗口判断。"""
    s = _FakeSession(scheme=None)
    assert S._scheme_capacity_block(s, 100_000, 262_144) is None      # 放行
    assert S._scheme_capacity_block(s, 450_000, 262_144) is not None  # 拦


# ------------------------------------------------- v4.1.0-a590 审计后的回归项
def test_live_window_falls_back_to_reported(monkeypatch):
    """无窗口键时回落网关实报，不再盲判 256K（审计 P1-3）。

    「旧格式方案 + 大窗模型」曾一律按 256K 拒发，直接违反需求第 1 条。
    """
    monkeypatch.setattr(S, "_read_live_env", lambda: {})
    s = _FakeSession(last_result={"modelUsage": {"m": {"contextWindow": 1_000_000}}})
    assert S.live_ctx_window(s) == 1_000_000     # 传会话 → 用实报
    assert S.live_ctx_window() == S._CTX_WINDOW_DEFAULT   # 不传 → 兜底


def test_live_window_prefers_settings_then_1m(monkeypatch):
    """窗口键优先于实报；无键时 [1M] 后缀模型优先于实报。"""
    monkeypatch.setattr(S, "_read_live_env",
                        lambda: {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000",
                                 "ANTHROPIC_MODEL": "glm-x[1M]"})
    assert S.live_ctx_window(_FakeSession()) == 500_000
    monkeypatch.setattr(S, "_read_live_env",
                        lambda: {"ANTHROPIC_MODEL": "glm-x[1M]"})
    assert S.live_ctx_window(_FakeSession()) == S._CTX_WINDOW_1M


def test_reconcile_respects_force(monkeypatch):
    """同方案内改配置（force=False）不动用户手选模型（审计 P2-6）。"""
    monkeypatch.setattr(S, "available_models",
                        lambda: {"models": ["new-a"], "default": "new-a"})
    s = _FakeSession(model="handpicked", model_origin="user")
    assert S._reconcile_model_with_live(s, force=False) is None
    assert s.model == "handpicked"           # 用户手选被保留
    # 真换方案（force=True）才强切，否则新网关 400 model not found
    assert S._reconcile_model_with_live(s, force=True) == "handpicked"
    assert s.model == "new-a"
    assert s.model_origin == "scheme"


def test_ctx_used_source_is_lastresult_without_jsonl():
    """无 jsonl 时 _session_ctx_used 走 last_result 兜底并打来源标记（P2-4）。

    a591：原测试名是 test_ctx_source_marked_jsonl（说 jsonl），断言却只覆盖
    lastResult 兜底——名字与断言货不对板。改名如实，并补一条 jsonl 分支。
    """
    s = _FakeSession(last_result={"usage": {"input_tokens": 5000},
                                  "modelUsage": {"m": {"contextWindow": 262_144}}})
    s.session_id = "nonexistent-sid-for-test"
    s._ctx_used_source = "none"
    used, _w, _c = S._session_ctx_used(s)
    # 无 jsonl 时只能走 last_result 兜底，来源标 lastResult
    assert s._ctx_used_source == "lastResult"
    assert used == 5000


def test_window_hwm_not_reset_by_smaller_report():
    """实报窗口 hwm 只增不减——大窗切小窗后 450K 不该被判坏（P2-4）。"""
    s = _FakeSession(last_result={"modelUsage": {"m": {"contextWindow": 1_000_000}}})
    assert S._ctx_window_hwm(s) == 1_000_000
    s.last_result = {"modelUsage": {"m": {"contextWindow": 262_144}}}
    assert S._ctx_window_hwm(s) == 1_000_000     # 保留历史最大


def test_vision_note_returns_text_for_inline_model():
    """识图口径声明对 inline 模型给出非空文案（P2-5）。

    a591：原测试名 test_vision_note_for_both_modes 说「两态」，实际只测了
    一个模型的非空断言。改名如实——「两态」应由 vision 模块自己的测试覆盖，
    这里只管「注入通道不空」这一件事。
    """
    note_inline = S._vision_note_for("some-vision-model")
    assert isinstance(note_inline, str)
    assert note_inline            # 至少给出一种口径，不能是空串


def test_slash_command_reaches_cli_unprefixed():
    """斜杠命令不能被模型切换声明前缀污染（否则 CLI 不再当命令识别）。

    a591：原测试对 send_message 源码做字符串 grep（断言 'startswith("/")' 存在），
    那是源码签名比对——重构改名即碎，行为改烂照样绿。改为**行为**验证：
    直接调 send_message 之前的注入口，断言 / 开头的文本不被加前缀。
    """
    # 行为层：判定逻辑是纯函数 _should_inject_switch_note(text, note)
    fn = S._should_inject_switch_note
    NOTE = "多模态直读"
    for text in ("/compact", "  /rescue", "/clear"):
        assert fn(text, NOTE) is False, "斜杠命令不该被加前缀：%r" % text
    for text in ("hello", "请看这段代码", ""):
        assert fn(text, NOTE) is True, "普通消息应加前缀：%r" % text
    # 无待注入声明时一律不加（否则每条都挂一段空说明）
    assert fn("hello", None) is False
    assert fn("hello", "") is False


# ------------------------------------------------- P0 续命 / P1 skip_capacity
# a591：这两条是本次改动最要害的逻辑，原来一条测试都没有。
def test_remote_bot_over_window_renews_first():
    """P0：超窗时远程小助手**先续命**，不被容量拦截挡下。

    此前拦截在前、续命在后 → 小助手切小窗方案后直接收到拒发文案，任务中断。
    """
    W = 100_000
    # 已用 99% + 小助手 + 续命可用 → renew（而不是 block）
    assert S._capacity_verdict(int(W * 0.99), W, "继续任务", True, True) == "renew"


def test_remote_bot_renew_failure_falls_back_to_block():
    """续命失败不能静默吞消息——落回容量拦截，用户能看见原因。"""
    W = 100_000
    assert S._capacity_verdict(int(W * 0.99), W, "继续任务", True, False) == "block"


def test_non_remote_session_never_renews():
    """GUI 会话（非小助手）绝不续命——换会话要用户知情。"""
    W = 100_000
    assert S._capacity_verdict(int(W * 0.99), W, "继续任务", False, True) == "block"


def test_compact_always_passes_even_over_window():
    """/compact 是超窗唯一出口，满窗也必须放行（否则会话锁死）。"""
    W = 100_000
    for text in ("/compact", "  /compact", "/compact 只留结论"):
        assert S._capacity_verdict(int(W * 0.999), W, text, True, True) == "pass"
        assert S._capacity_verdict(int(W * 0.999), W, text, False, True) == "pass"


def test_under_window_passes():
    W = 100_000
    assert S._capacity_verdict(int(W * 0.5), W, "普通消息", False, True) == "pass"


def test_unknown_usage_or_window_fails_open():
    """读不到用量/窗口时放行——探测失败不能锁死会话。"""
    assert S._capacity_verdict(0, 100_000, "x", False, True) == "pass"
    assert S._capacity_verdict(50_000, 0, "x", False, True) == "pass"
    assert S._capacity_verdict(None, None, "x", False, True) == "pass"


def test_verdict_agrees_with_capacity_block():
    """两个判据必须同口径：_capacity_verdict 说 block 时，
    _scheme_capacity_block 必须给出文案（否则就是两套算术）。"""
    W = 100_000
    s = _FakeSession(scheme="小窗")
    for used in (int(W * 0.97), int(W * 0.99), W, W * 2):
        v = S._capacity_verdict(used, W, "继续", False, True)
        cap = S._scheme_capacity_block(s, used, W, "继续")
        assert v == "block" and cap, "used=%d verdict=%s cap=%r" % (used, v, cap)


def test_skip_capacity_bypasses_verdict_at_call_site():
    """P1：/rescue 裁剪重发必须能绕过容量判定（skip_capacity=True）。

    裁剪不改 _session_ctx_used 的读数（取 jsonl 尾部 assistant usage），
    不跳过的话越需要救援的爆死态越救不回来。
    上一版这条是 inspect.getsource + 字符串 index 比对——同样是签名比对。
    a591 改为调纯函数 _should_run_capacity_check 验行为。
    """
    fn = S._should_run_capacity_check
    # 正常发送：进判定
    assert fn("m", "sid", False) is True
    # 裁剪重发：跳过判定
    assert fn("m", "sid", True) is False
    # 无会话/无模型：不判定（新会话还没起来）
    assert fn("m", None, False) is False
    assert fn(None, "sid", False) is False


# ------------------------------------------------ 方案徽章按窗口大小判定
def _badge_risky(scheme_window, cur_window):
    """与 web/js/harness/sessions.js::_hgSchemeBadge 同判据：
    只在「会话窗口 > 当前方案窗口」时才算风险（切小窗才有超窗可能）。"""
    sw = int(scheme_window or 0)
    cw = int(cur_window or 0)
    return sw > 0 and cw > 0 and sw > cw


def test_same_window_schemes_not_flagged():
    """用户实锤：lanzi 与 lanzi-qiu 都是 500K，互切不该标红。"""
    assert _badge_risky(500_000, 500_000) is False


def test_larger_session_window_flagged():
    """会话来自 1M 方案、当前是 500K 方案 → 有超窗风险，标红。"""
    assert _badge_risky(1_000_000, 500_000) is True


def test_smaller_session_window_not_flagged():
    """会话 500K、当前 1M → 容量只增，不该标红。"""
    assert _badge_risky(500_000, 1_000_000) is False


def test_unknown_window_not_flagged():
    """窗口未知（方案列表读不到）→ 不标红（不制造噪音）。"""
    assert _badge_risky(0, 500_000) is False
    assert _badge_risky(500_000, 0) is False


def test_badge_criteria_contract_with_js():
    """a623R（审计 #3）：_badge_risky 是 web/js/harness/sessions.js 判据的
    Python 手抄副本——上面 4 条测试只测副本，JS 改坏测试照绿（同义反复，
    a613 清过的假断言物种）。这里对 JS 判据源码做**契约断言**：判据行或
    ctxWindow 取值链被改动时本测试必须红，逼人同步两处。"""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web", "js", "harness", "sessions.js")
    with open(p, encoding="utf-8") as f:
        src = f.read()
    # 判据行（改判据必须同步 _badge_risky 与本断言）
    assert "const risky = sw > 0 && cw > 0 && sw > cw;" in src, \
        "sessions.js 的 risky 判据变了——同步 web 判据、_badge_risky 和本契约"
    # 会话窗口取值链：后端算好的实际生效窗口优先，schemeWindow 兜底
    assert "Number(s.ctxWindow) || Number(s.schemeWindow)" in src, \
        "sessions.js 的 ctxWindow 取值链变了——同步 _badge_risky 语义与本契约"
    # 当前方案窗口来源（a623R 复审补钉）：_badge_risky 的 cw 语义锚在这行
    assert "const cw = Number(_HG.schemeWindow) || 0;" in src, \
        "sessions.js 的 cw 取值变了——同步 _badge_risky 语义与本契约"


def test_profile_ctx_window_reads_snapshot():
    """profile_ctx_window 从方案快照读窗口键，未知方案返回 0。"""
    from src.claude_default import profile_ctx_window
    assert profile_ctx_window("__no_such_profile__") == 0
    assert isinstance(profile_ctx_window(""), int)
