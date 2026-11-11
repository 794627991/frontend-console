# -*- coding: utf-8 -*-
"""回滚边界双格式回归（a462）。

实锤背景：现行 Claude CLI 的转写不再写 {"type":"result"} 行（实测本机
30 份转写全为 0），而三个 _rewind_* 函数全靠它找回合边界——「回滚到此处」
自 v2.28 上线以来必然报「锚点所在回合没有完整收尾」。

修复后边界双格式兼容：旧 = result 行；新 = 真实人类消息行（user 型、
非 isMeta、content 无 tool_result）。本测试用两种合成转写直打生产函数，
不依赖真实 ~/.claude 目录。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness import routes as R  # noqa: E402


def _mk(lines):
    """合成转写文件并 monkeypatch 路径解析。返回 (path, cleanup)。"""
    d = tempfile.mkdtemp(prefix="rw_test_")
    proj = os.path.join(d, "proj")
    os.makedirs(proj)
    p = os.path.join(proj, "SID.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for o in lines:
            # CLI 转写是紧凑 JSON（无空格分隔符）——生产代码的子串预门
            # （'"type":"user"'）按它设计，测试数据必须同形态
            f.write(json.dumps(o, ensure_ascii=False,
                               separators=(",", ":")) + "\n")
    orig = R._jsonl_path_for
    R._jsonl_path_for = lambda sid: p if sid == "SID" else orig(sid)
    return p, lambda: (R.__setattr__("_jsonl_path_for", orig),
                       __import__("shutil").rmtree(d, ignore_errors=True))


def _asst(text, ts, extra=None):
    o = {"type": "assistant", "timestamp": ts,
         "message": {"content": [{"type": "text", "text": text}]}}
    if extra:
        o.update(extra)
    return o


def _human(text, ts, meta=False):
    return {"type": "user", "timestamp": ts, "isMeta": meta,
            "message": {"content": text}}


def _toolres(ts):
    return {"type": "user", "timestamp": ts,
            "message": {"content": [{"type": "tool_result",
                                     "tool_use_id": "t1", "content": "ok"}]}}


def _result(ts):
    return {"type": "result", "timestamp": ts, "result": "done"}


def _kept_texts(path):
    out = []
    for ln in open(path, encoding="utf-8"):
        o = json.loads(ln)
        c = (o.get("message") or {}).get("content")
        if o.get("type") == "assistant":
            out.append(c[0]["text"] if isinstance(c, list) else c)
        elif o.get("type") == "user" and isinstance(c, str):
            out.append("U:" + c)
        elif o.get("type") == "result":
            out.append("<result>")
    return out


NEW_FMT = [
    _human("第一问", "2026-01-01T10:00:00"),
    _asst("第一答开头", "2026-01-01T10:00:05"),
    _toolres("2026-01-01T10:00:10"),
    _asst("第一答收尾", "2026-01-01T10:00:20"),
    _human("第二问", "2026-01-01T10:01:00"),
    _asst("第二答", "2026-01-01T10:01:05"),
    _toolres("2026-01-01T10:01:10"),
    _asst("第二答收尾", "2026-01-01T10:01:20"),
    _human("第三问", "2026-01-01T10:02:00"),
    _asst("第三答", "2026-01-01T10:02:05"),
    _human("[Image: xxx]", "2026-01-01T10:02:06", meta=True),   # isMeta 注入
    _asst("第三答收尾", "2026-01-01T10:02:20"),
]

OLD_FMT = [
    _human("第一问", "2026-01-01T10:00:00"),
    _asst("第一答", "2026-01-01T10:00:05"),
    _result("2026-01-01T10:00:20"),
    _human("第二问", "2026-01-01T10:01:00"),
    _asst("第二答", "2026-01-01T10:01:05"),
    _result("2026-01-01T10:01:20"),
]


def test_anchor_new_format():
    """新格式：锚点=第二答 → 截到第三问之前（isMeta 行不当边界）。"""
    p, cleanup = _mk(NEW_FMT)
    try:
        ok, msg = R._rewind_jsonl_anchor("SID", "第二答")
        assert ok, msg
        kept = _kept_texts(p)
        assert kept == ["U:第一问", "第一答开头", "第一答收尾",
                        "U:第二问", "第二答", "第二答收尾"], kept
    finally:
        cleanup()


def test_anchor_old_format_unchanged():
    """旧格式行为保持：锚点=第一答 → 保留到其 result（含）。"""
    p, cleanup = _mk(OLD_FMT)
    try:
        ok, msg = R._rewind_jsonl_anchor("SID", "第一答")
        assert ok, msg
        assert _kept_texts(p) == ["U:第一问", "第一答", "<result>"]
    finally:
        cleanup()


def test_anchor_tail_is_noop():
    """锚点在最后一回合且其后无内容 → 明确报没有可回退（不再是误报
    「没有完整收尾」）。"""
    p, cleanup = _mk(NEW_FMT)
    try:
        ok, msg = R._rewind_jsonl_anchor("SID", "第三答收尾")
        assert not ok and "没有可回退" in msg, (ok, msg)
    finally:
        cleanup()


def test_turns_new_format():
    """新格式回退 1 回合：删掉最后一段（第三问起）。"""
    p, cleanup = _mk(NEW_FMT)
    try:
        ok, msg = R._rewind_jsonl("SID", 1)
        assert ok, msg
        assert _kept_texts(p)[-1] == "第二答收尾"
    finally:
        cleanup()


def test_turns_new_format_single_turn():
    """单回合转写（本机实测形态）不可整段回退。"""
    p, cleanup = _mk([_human("唯一一问", "2026-01-01T10:00:00"),
                      _asst("唯一一答", "2026-01-01T10:00:05")])
    try:
        ok, msg = R._rewind_jsonl("SID", 1)
        assert not ok, (ok, msg)
    finally:
        cleanup()


def test_turn_start_predicate():
    """边界判据：真人类消息 ✓；tool_result ✗；isMeta ✗；assistant ✗。"""
    def J(o):
        return json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    assert R._is_turn_start(J(_human("hi", "t")))
    assert R._is_turn_start(J(
        {"type": "user", "timestamp": "t",
         "message": {"content": [{"type": "text", "text": "hi"},
                                 {"type": "image", "source": "x"}]}}))
    assert not R._is_turn_start(J(_toolres("t")))
    assert not R._is_turn_start(J(_human("m", "t", meta=True)))
    assert not R._is_turn_start(J(_asst("a", "t")))
    assert not R._is_turn_start(J(_result("t")))
    # 内容文本里包含 "type":"user" 字面量不得误判（子串预门 + parse 双验）
    assert not R._is_turn_start(J(_asst('说着 "type":"user" 的例子', "t")))


def test_harness_version_parse():
    """a467：版本号自动解析——首个 v4.1.0-aNNN 命中、跨版本前缀不误取。"""
    from src.harness import _parse_harness_version as P
    assert P(["v4.1.0-a464 复审", "v4.1.0-a400 x"]) == "4.1.0-a464"
    assert P(["v3.5.99 老", "v4.1.0-a12 y"]) == "4.1.0-a12"
    assert P(["v3.5.99 老", "无关"]) == ""
    assert P([]) == ""
    assert P(["v4.1.0-a123R 修"]) == "4.1.0-a123"
