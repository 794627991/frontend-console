# -*- coding: utf-8 -*-
"""超窗救援（/rescue）规划纯函数回归（a463）。

场景：API 400 爆窗、/compact 压不动的爆死态——丢中部最大回合回安全余量，
首回合任务定义与最近内容保留；末回合被丢时由路由自动重发其指令。
本文件测 _rescue_plan 的裁剪策略（纯函数，不依赖会话/进程）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness import routes as R  # noqa: E402


def _lines(specs):
    """specs: [('human'|'asst'|'toolres'|'meta'|'result', text, size)]"""
    out = []
    for kind, text, size in specs:
        if kind == "human":
            o = {"type": "user", "timestamp": "t",
                 "message": {"content": text}}
        elif kind == "asst":
            o = {"type": "assistant", "timestamp": "t",
                 "message": {"content": [{"type": "text", "text": text}]}}
        elif kind == "toolres":
            o = {"type": "user", "timestamp": "t",
                 "message": {"content": [{"type": "tool_result",
                                          "tool_use_id": "x", "content": text}]}}
        elif kind == "meta":
            o = {"type": "api-request-blob", "timestamp": "t", "blob": text}
        else:
            o = {"type": "result", "timestamp": "t", "result": text}
        # 撑大体积（content 重复填充）
        key = "blob" if kind == "meta" else None
        if key:
            o[key] = text * max(1, size // max(1, len(text)))
        elif kind in ("asst", "toolres") and size > len(text):
            c = o["message"]["content"]
            if isinstance(c, list):
                c[-1]["text" if c[-1].get("type") == "text" else "content"] = \
                    text * (size // max(1, len(text)))
        out.append(json.dumps(o, ensure_ascii=False, separators=(",", ":")))
    return out


def test_rescue_drops_biggest_middle_keeps_first_and_tail():
    """5 回合：中部第 2 回合巨大 → 只丢它，首回合与末回合保留。"""
    L = _lines([
        ("human", "任务定义：做X", 20),
        ("asst", "好的开始", 20),
        ("human", "第二问", 10),
        ("asst", "小答", 10),
        ("human", "第三问", 10),
        ("asst", "巨量工具输出" * 100, 1400),      # 第 2 回合（0 基）巨大
        ("human", "第四问", 10),
        ("asst", "小答4", 10),
        ("human", "最近一问", 10),
        ("asst", "最近一答", 10),
    ])
    # used=3000 tokens / total≈1500 chars → ratio=2；window=2000 → target=1240
    plan, err = R._rescue_plan(L, used=3000, window=2000)
    assert plan, err
    assert 2 in plan["drop"], plan["drop"]
    assert 0 not in plan["drop"] and 4 not in plan["drop"]
    assert plan["est_after"] <= plan["target"]


def test_rescue_tail_explosion_drops_tail_first():
    """爆炸在末回合（巨量工具输出在最后）→ 末回合被丢（resend 路径激活）。"""
    L = _lines([
        ("human", "任务定义", 20),
        ("asst", "ok", 10),
        ("human", "第二问", 10),
        ("asst", "答", 10),
        ("human", "最后一问", 10),
        ("asst", "爆炸输出" * 200, 1400),
    ])
    plan, err = R._rescue_plan(L, used=3000, window=2000)
    assert plan, err
    assert 2 in plan["drop"], plan["drop"]        # 末回合（0 基 2）被丢
    assert plan["est_after"] <= plan["target"]


def test_rescue_noop_when_under():
    L = _lines([("human", "q", 10), ("asst", "a", 10),
                ("human", "q2", 10), ("asst", "a2", 10)])
    plan, err = R._rescue_plan(L, used=10, window=100000)
    assert plan is None and "无需救援" in err


def test_rescue_needs_two_turns():
    L = _lines([("human", "q", 10), ("asst", "a", 10)])
    plan, err = R._rescue_plan(L, used=9999, window=100)
    assert plan is None and "两个完整回合" in err


def test_rescue_first_turn_too_big():
    """首回合独大：丢光中部仍超限 → 如实报错（不产生半吊子计划）。"""
    L = _lines([
        ("human", "任务定义" * 300, 1200),
        ("asst", "ok", 10),
        ("human", "第二问", 10),
        ("asst", "答", 10),
        ("human", "第三问", 10),
        ("asst", "答3", 10),
    ])
    plan, err = R._rescue_plan(L, used=3000, window=1000)
    assert plan is None and "首回合" in err


def test_rescue_meta_lines_not_double_counted():
    """api-request-blob 等元数据行是正文副本——不计入回合体量与 total。

    构造：三回合正文都很小，但第一回合段内塞了 5000 字符的请求快照行。
    若 meta 被计入：total 虚高 → 比率被稀释 → 欠裁（est_after 仍超线）。"""
    blob = json.dumps({"type": "api-request-blob", "timestamp": "t",
                       "blob": "y" * 5000}, ensure_ascii=False,
                      separators=(",", ":"))
    L = _lines([("human", "任务定义", 20), ("asst", "答1", 20)]) + [blob] + \
        _lines([("human", "q2", 20), ("asst", "答2" * 50, 100)]) + \
        _lines([("human", "q3", 20), ("asst", "答3" * 50, 100)])
    # 真实用量 1200 tokens、窗口 1000（target 620）——正文只有 ~260 字符，
    # 比率=1200/260≈4.6：必须裁掉一个百字符级回合才回线
    plan, err = R._rescue_plan(L, used=1200, window=1000)
    assert plan, err
    # 元数据行不计入：total 远小于全部原始行字符数
    assert plan["total_chars"] < sum(len(x) for x in L)
    assert plan["est_after"] <= plan["target"]
    assert plan["drop"], "欠裁（ratio 被元数据稀释的假象）"
