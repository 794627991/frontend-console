# -*- coding: utf-8 -*-
"""harness.audit —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import sys
import tempfile
import logging
log = logging.getLogger(__name__)
from .. import app_state as _st
from .consts import _SRC_DIR


# ---- from claude_harness.py:856 (_AUDIT_EDIT_TOOLS) ----


# ---------------------------------------------------------------------------
# v2.34 light 形态回合结算审计（三角色强制机制的兜底层）。
# 背景：light 形态（主会话=轻快模型）下「代码修改必须走 dev+reviewer」纯靠
# 引导词软约束——失效模式：模型偷懒自己 Edit、把多行改动自判为微调免审、
# dev 交付后跳过 reviewer 直接答用户、分多次小改切片逃逸。strong 形态有
# 结构禁权不管；light 主会话要干杂活不能禁工具。审计=用客观事实（stream-json
# 事件流的工具调用记录）判定，不靠模型自判；纯本地字符串/计数，零 token。
# ---------------------------------------------------------------------------
_AUDIT_EDIT_TOOLS = ("Edit", "Write", "MultiEdit",
                     "NotebookEdit")   # 直改类工具（主会话调用才计）

# ---- from claude_harness.py:868 (_audit_nlines) ----


def _audit_nlines(s):
    """字符串行数（空串=0）——审计行数口径的基础件。"""
    s = str(s or "")
    return s.count("\n") + 1 if s else 0

# ---- from claude_harness.py:874 (_audit_lines) ----


def _audit_lines(name, inp):
    """v2.34 审计行数口径（写死于此，判定要可复现）；v2.49 补 MultiEdit：
    - Edit：max(old_string, new_string) 行数——替换影响按两侧较大跨度计。
      不用行数差：删 30 行补 1 行的「瘦身式大改」差值为负/极小，会逃逸。
    - Write：新文件全文行数（空 content 至少计 1——整文件清空也是变更）；
      覆盖写时旧内容事件流里不可得，按全量新增计。
    - MultiEdit（v2.49）：各编辑块按 Edit 口径（max(old,new)）求和——原先
      不在 _AUDIT_EDIT_TOOLS 里整类计 0，是行数口径的逃逸口（分级路由的
      上限放大到百行级后必须堵上）。
    - NotebookEdit：new_source（cell 新内容）行数；delete 无内容变更计 0。"""
    try:
        if name == "Edit":
            return max(_audit_nlines(inp.get("old_string")),
                       _audit_nlines(inp.get("new_string")))
        if name == "Write":
            # 空 content 也是实质变更（整文件清空/覆盖写空），至少计 1——
            # 计 0 会让「把文件写空」逃逸审计
            return max(1, _audit_nlines(inp.get("content")))
        if name == "MultiEdit":
            total = 0
            for e in inp.get("edits") or []:
                if isinstance(e, dict):
                    total += max(_audit_nlines(e.get("old_string")),
                                 _audit_nlines(e.get("new_string")))
            return total
        if name == "NotebookEdit":
            return _audit_nlines(inp.get("new_source"))
    except Exception:
        pass
    return 0

# ---- from claude_harness.py:906 (_AUDIT_ROLES) ----


# v2.52：_audit_file_key（v2.49 文件数口径归一键）随文件数判定一起删除
# ——判定只看单次直改行数，无文件数消费方（tests 同步引用已清）。


# 角色集合（v2.51）：designer 只设计（无直改；派发旗是 v2.54 设计档的
# 豁免依据——不产生直改、不算已审）；reviewer 是唯一
# 「审过」信号（结算追责与事中闸开闸都看它）。dev/executor/coder 已退役
# 不再识别。
_AUDIT_ROLES = ("designer", "reviewer")

# ---- from claude_harness.py:917 (_audit_dispatch_role) ----


def _audit_dispatch_role(n, inp, ids=None):
    """主会话派发/续派 designer|reviewer 的识别（纯函数，_audit_tally
    调用）：返回 "designer"/"reviewer"/None。
    - Task/Agent：按 subagent_type；
    - SendMessage 续派：按 input.to 识别——三形态：裸名（"designer"）、
      带 [ref]（"designer [3fa9c1]"）、裸 agentId（查 ids 映射——由
      Task 结果回填，见 _audit_tally_result）。
    已知缺口（做不了硬匹配，如实记录）：①「worker [ref]」/「worker
    agentId」形态——to 里只有通用名+引用，无角色名可判（ids 映射键是
    agentId 不含 ref 短码，两者无法稳定互推）；②跨进程/跨实例的 agentId
    ——本会话 _audit 只见本进程的 Task 结果，别处派的 id 查不到。两类
    续派在结算里仍不计派发标记（保守漏计，不误计）。"""
    if n in ("Task", "Agent"):
        st = str(inp.get("subagent_type") or inp.get("agent_type") or "")
        return st if st in _AUDIT_ROLES else None
    if n == "SendMessage":
        to = str(inp.get("to") or "").strip()
        base = to.split("[")[0].strip()
        if base in _AUDIT_ROLES:
            return base
        return (ids or {}).get(to)
    return None

# ---- from claude_harness.py:941 (_audit_hook_settings_path) ----


def _audit_hook_settings_path():
    """写 light 形态会话的 --settings 临时文件（直改事中闸注入；判定见
    harness_roles.audit_gate_check——审计档（达轻审线未派 reviewer）与
    设计档（达设计线未派 designer）任一命中即拦，派过对应代理即开闸）。

    内容只有 hooks 键：Edit/Write/MultiEdit/NotebookEdit 的 PreToolUse 指向
    `--audit-hook` 子命令（它查 /audit_gate 决定放行/拦截，见
    harness_audit_hook.py）。双形态命令与 _ask_mcp_cfg_path 同构：源码=
    python main.py，打包=exe 自身（src 不在盘上）。

    返回 settings 路径；任何失败返回 None（注入失败不阻塞会话启动——
    铁律：闸是增强不是依赖，回合结算审计仍在兜底）。"""
    try:
        if getattr(sys, "frozen", False):
            parts = [sys.executable, "--audit-hook"]
        else:
            # 路径正斜杠：cmd shim 会吞反斜杠转义（_ask_mcp_cfg_path 实测坑）
            parts = [sys.executable or "python",
                     os.path.join(_SRC_DIR, "main.py").replace("\\", "/"),
                     "--audit-hook"]
        # 每段双引号：解释器装在 Program Files 等带空格路径时裸拼会断
        cmd = " ".join('"%s"' % p for p in parts)
        cfg = {"hooks": {"PreToolUse": [{
            "matcher": "Edit|Write|MultiEdit|NotebookEdit",
            "hooks": [{"type": "command", "command": cmd}]}]}}
        fd, p = tempfile.mkstemp(suffix=".json", prefix="claude_audit_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        return p
    except Exception:
        return None

# ---- from claude_harness.py:974 (_AUDIT_LOG_MAX) ----


# v2.34.1：审计警示卡持久化（~/.serialconsole_pro/harness_audit_log.jsonl，
# 每行 {sid, ts, text}，512K 截半——vision_mcp.log 同款惯例）。背景：warn/
# 降级/中断档的卡只 emit 进事件缓冲，transcript_for 回放（解析 jsonl）没有
# 对应行——刷新/切会话即失；auto 档实时卡与续发消息也是两份不同文本。
# 现统一：卡文本=落盘文本=（auto 档）续发消息文本，同一字符串三处共用；
# [审计] user 行在 transcript_for 里不再单独出（卡由本 log 回放，无双份）。
_AUDIT_LOG_MAX = 512 * 1024

# ---- from claude_harness.py:983 (_AUDIT_MSG_PREFIX) ----

# v2.34.2（复审 R1 收口）：审计续发消息的唯一句式前缀。send_message 的
# 「不画气泡」与 transcript_for 的「跳过不出行」都按它判定，与 _audit_settle
# 拼消息处三处引用同一常量——防文案漂移导致判定失效。刻意比 "[审计]" 长：
# 用户手打的以「[审计]」开头的普通消息（质疑机制时引用前缀等）不能被吞，
# 必须照常画气泡/回放（曾用宽前缀 startswith("[审计]")，用户视角「我发的
# 话凭空没了」）。warn/中断/exit 档的卡文案不走 send_message，不受影响。
_AUDIT_MSG_PREFIX = "[审计] 本回合检测到:"

# ---- from claude_harness.py:991 (_audit_iso_now) ----


def _audit_iso_now():
    """UTC ISO（Z 后缀，与 CLI 转写 timestamp 同款格式，可直接字符串比较）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

# ---- from claude_harness.py:997 (_audit_log_append) ----


def _audit_log_append(sid, text):
    """审计卡落盘（追加一行；超限截半保后半）。失败静默——回放缺卡不致命。"""
    try:
        p = os.path.join(_st.HOME_DIR, "harness_audit_log.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"sid": sid, "ts": _audit_iso_now(),
                                "text": str(text or "")[:4000]},
                               ensure_ascii=False) + "\n")
        if os.path.getsize(p) > _AUDIT_LOG_MAX:
            with open(p, "r", encoding="utf-8") as f:
                lns = f.readlines()
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(lns[len(lns) // 2:])
    except Exception:
        pass

# ---- from claude_harness.py:1014 (_audit_log_read) ----


def _audit_log_read(sid):
    """读该会话的全部审计卡（转写回放合并用）。返回 role='audit' 行列表。"""
    out = []
    try:
        p = os.path.join(_st.HOME_DIR, "harness_audit_log.jsonl")
        with open(p, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                if o.get("sid") == sid and o.get("text"):
                    out.append({"role": "audit", "text": str(o["text"])[:4000],
                                "ts": o.get("ts") or ""})
    except Exception:
        pass
    return out
