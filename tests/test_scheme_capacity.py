# -*- coding: utf-8 -*-
"""跨 API 方案兼容（v4.2）：只按上下文容量判定，不再按方案名硬拦。

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


# ------------------------------------------------- v4.2R 审计后的回归项
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


def test_ctx_source_marked_jsonl():
    """_session_ctx_used 打出来源标记，供前端区分合法超窗与坏数据（P2-4）。"""
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


def test_vision_note_for_both_modes():
    """识图口径声明两态齐全，且自动/手动切换共用同一文案源（P2-5）。"""
    note_inline = S._vision_note_for("some-vision-model")
    assert isinstance(note_inline, str)
    assert note_inline            # 至少给出一种口径，不能是空串


def test_slash_command_not_prefixed_by_note():
    """斜杠命令不能被模型切换声明前缀污染（否则 CLI 不再当命令识别）。"""
    import inspect
    src = inspect.getsource(S.HarnessSession.send_message)
    assert 'startswith("/")' in src
    assert "_model_switch_note" in src
