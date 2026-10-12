# -*- coding: utf-8 -*-
"""v3.5.100/101 用户边界审计制状态机测试（全审 P4 补覆盖）。
直测 HarnessSession._audit_settle 内联判定：桩掉 emit/_audit_send/
_audit_state/_audit_card，验证 lines 跨 AI 回合累计、审后再审、fired_at
水位防重复、boundary 清零。"""
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# R1（复核残留）：隔离 CONFIG_FILE（必须在 import src.* 前改 app_state）——
# design_limit 走 roles_cfg 读它，不隔离则读用户真 config，设计线值漂移
# 会让本套件假失败/假通过
import src.app_state as _st   # noqa: E402
_TMP = tempfile.mkdtemp(prefix="audit_boundary_test_")
_st.CONFIG_FILE = os.path.join(_TMP, "config.json")
os.environ.setdefault("HARNESS_AGENTS_DIR", _TMP)
# 线值显式钉死（免审100/轻审250/设计150）——R2 后 settle 用单读真实
# audit_limits/design_limit，桩的 _audit_state limits 已弃用，不钉会漂
import json as _json
with open(_st.CONFIG_FILE, "w", encoding="utf-8") as _f:
    _json.dump({"harness_roles": {"design_max_lines": 150,
                                  "l1_max_lines": 100,
                                  "l2_max_lines": 250}}, _f)

from src.harness.session import HarnessSession   # noqa: E402


def _mk_session():
    """最小桩会话：不真起 CLI 进程，只挂审计状态机要用的属性。"""
    s = HarnessSession.__new__(HarnessSession)
    s.sid = "t"
    s._audit = {"lines": 0, "files": [], "designer": False,
                "designFired": False, "reviewer": False, "rev_at": 0,
                "fired_at": 0, "streak": 0, "ids": {}, "pending": {}}
    s._audit_lock = __import__("threading").Lock()
    s._audit_state = lambda: ("auto", (100, 200, 250), False)   # light: 免审100/轻审250
    s._audit_card = lambda text: None
    s._audit_send = lambda text: None
    s.emit = lambda o: None
    return s


def test_cross_result_accumulate():
    """两个 AI 回合各 60 行（单回合不超线）——累计 120 超免审线触发。"""
    s = _mk_session()
    s._audit["lines"] = 60
    s._audit_settle("result")
    assert not s._audit["fired_at"], "单回合 60 行不该触发"
    s._audit["lines"] = 120
    s._audit_settle("result")
    assert s._audit["fired_at"] == 120, "累计超线应触发"


def test_review_then_more():
    """触发→派 reviewer（rev_at 记水位）→新增 30 行（<线）不触发→再增 90 行（累计新增>线）再触发。
    designer=True 排除设计档干扰（本测试聚焦审线）。"""
    s = _mk_session()
    s._audit["designer"] = True
    s._audit["lines"] = 120
    s._audit_settle("result")                       # 触发
    s._audit["reviewer"] = True
    s._audit["rev_at"] = s._audit["lines"]          # 模拟 tally 写入
    s._audit["lines"] = 150
    s._audit_settle("result")
    assert s._audit["fired_at"] == 120, "新增 30 行(<免审线)不该再触发"
    s._audit["lines"] = 240
    s._audit_settle("result")
    assert s._audit["fired_at"] == 240, "审后新增 120 行(>线)应再触发"


def test_boundary_reset():
    """boundary 清零：用户消息开新大回合，全部计数归零。"""
    s = _mk_session()
    s._audit.update({"lines": 300, "designer": True, "reviewer": True,
                     "rev_at": 250, "fired_at": 200, "streak": 2})
    # 模拟 send_message 边界清零块（与实现同字段）
    with s._audit_lock:
        s._audit.update({"lines": 0, "files": [], "designer": False,
                         "designFired": False, "reviewer": False,
                         "rev_at": 0, "fired_at": 0, "streak": 0})
    s._audit["lines"] = 120
    s._audit_settle("result")
    assert s._audit["fired_at"] == 120, "新大回合 120 行应重新触发（设计/审旗已随边界清）"


def test_design_line():
    """设计线独立判定（strong 桩：审线 250 不干扰，200 行只达设计线 150）：
    未派 designer 触发；派过后同水位不再触发。"""
    s = _mk_session()
    s._audit_state = lambda: ("auto", (100, 200, 250), True)   # strong：需审线=250
    s._audit["lines"] = 200
    s._audit_settle("result")
    assert s._audit["fired_at"] == 200, "达设计线(150)未派 designer 应触发"
    s._audit["designer"] = True
    s._audit["lines"] = 210
    s._audit_settle("result")
    assert s._audit["fired_at"] == 200, "designer 在场不该再触发设计档"


def test_designer_flag_cross_result():
    """designer 旗跨 AI 回合保留：触发过一次后，后续纯实施回合不再触发设计档。"""
    s = _mk_session()
    s._audit["designer"] = True   # 前回合派的
    s._audit["lines"] = 300
    s._audit_settle("result")     # 审线触发（fired_at=300），设计档被旗豁免
    s._audit["lines"] = 360
    s._audit_settle("result")     # 新增量超线再触发——但设计档仍被旗豁免
    assert s._audit["designer"] is True, "designer 旗不该被结算清掉"
