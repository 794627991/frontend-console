# -*- coding: utf-8 -*-
"""harness.audit —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import re
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
# dev 交付后跳过 reviewer 直接答用户、分多次小改切片逃逸。mid 形态同受
# 审计线兜底；heavy 最信任档在上游 _audit_state 返回 None 全免。
# v3.5.51（用户拍板「至少等改完才咬」）：事中闸（PreToolUse hook 中途拦截）
# 退役——审计统一回合结束结算追责（audit_hook.py/_audit_gate 保留兼容但
# live 不再注入）。审计=用客观事实（stream-json 事件流的工具调用记录）判定，不靠模型自判；纯本地
# 客观事实（stream-json 事件流的工具调用记录）判定，不靠模型自判；纯本地
# 字符串/计数，零 token。
# ---------------------------------------------------------------------------
_AUDIT_EDIT_TOOLS = ("Edit", "Write", "MultiEdit",
                     "NotebookEdit")   # 直改类工具（主会话调用才计）

# ---- from claude_harness.py:868 (_audit_nlines) ----


def _audit_nlines(s):
    """字符串行数（空串=0）——审计行数口径的基础件。"""
    s = str(s or "")
    return s.count("\n") + 1 if s else 0

# 纯文档后缀（小写，含点）——_audit_lines 对这些目标不计行数（见该函数 docstring）
_AUDIT_DOC_EXTS = (".md", ".markdown", ".mdx", ".txt", ".rst", ".adoc")

# 测试用途路径豁免（v4.0.2，用户拍板「所有测试用途的脚本不应该计算」）：
# 审计线管的是**程序风险**（会不会把产品搞坏），测试/探针脚本只影响
# 验证面，写多少行都不进产品。按路径判（目录名 + 文件名前缀）——
# 项目约定 tests/ 目录、tools/_ 前缀的探针脚本（_probe_*/_stress_*），
# 以及 test_*.py / *_test.js / *.spec.js 这类命名。
# v4.0.4（复审实锤逃逸）：原实现只看「任意段命中」，三条实测逃逸——
#   tests/../src/harness/session.py → 豁免（产品代码！）
#   src/tests/../audit.py          → 豁免
#   src/_scan_big.py               → 豁免（前缀无目录域）
# 修法：normpath 消 .. → 锚定仓库根 → 只认**相对仓库根的首段**目录，
# 前缀探针组限定 tools/（本项目私有约定，外溢即逃逸面）。
_AUDIT_TEST_DIRS = ("tests", "testing", "test", "__tests__", "e2e",
                    "fixtures")   # spec 退役：本仓库无证据，specs/ 是文档
_AUDIT_TEST_PREFIX_ANY = ("test_",)          # 业界命名契约，全仓库生效
_AUDIT_TEST_PREFIX_TOOLS = ("_probe_", "_stress_", "_selftest", "_smoke",
                            "_ask_", "_busy_", "_chain_", "_analyze_",
                            "_scan_", "_white_", "_prof_", "_agents_",
                            "_vision_")      # 本项目 tools/ 私有约定
_AUDIT_TEST_SUFFIX = ("_test.py", "_test.js", "_test.ts", ".test.js",
                      ".test.ts", ".spec.js", ".spec.ts")


def _audit_normalize(path):
    """规范化路径：消 `..`/`.`/重复分隔符，统一正斜杠小写。

    v4.0.5（复审实锤）：**不能锚定「运行时代码所在目录」**。审计代码跑在
    后端进程里，而会话 cwd 可能是 worktree / 用户项目 / 发布版 exe 内——
    实测 `_SRC_DIR` 上一级作根会让 worktree 里 `tests/test_x.py` 照样计
    501 行（需求1 在多数场景失效）。逃逸面只需 normpath 就能堵：
    `tests/../src/harness/session.py` → `src/harness/session.py`，不再含
    测试段，自然计入。
    """
    try:
        p = os.path.normpath(str(path or "")).replace("\\", "/")
    except Exception:
        return ""
    return p.lower()


def _audit_prefixed(name, prefixes):
    """文件名是否命中前缀组。`_probe_` 同时匹配 `_probe.py`（尾下划线可省）
    ——探针脚本既有 `_probe_gate.py` 也有 `_probe.py` 两种叫法，边界必须
    是「点或下划线」（防 `_probeable.py` 这类误伤）。"""
    for pre in prefixes:
        if name.startswith(pre):
            return True
        base = pre.rstrip("_")
        if base != pre and name.startswith(base) \
                and name[len(base):len(base) + 1] in (".", "_"):
            return True
    return False


def _audit_is_test_path(path):
    """路径是否属测试用途（命中即不计行数）。大小写不敏感。

    三级判据（v4.0.5）：① normpath 消 `..` 后仍含测试目录段；② 文件名前缀
    （`test_` 全仓；`_probe_`/`_scan_` 等探针组限 `tools/`）；③ 测试后缀。
    深层同名目录（`src/tests/`）按「测试根就在路径中」处理——本项目不存在
    名为 tests 的产品目录，且目录域判据过窄会让用户项目里的
    `pkg/tests/test_x.py` 失效（需求1 的本意就是测试脚本别计入）。
    """
    rel = _audit_normalize(path)
    if not rel:
        return False           # 取不到路径：保守计入（不敢豁免未知目标）
    parts = [x for x in rel.split("/") if x and x != "."]
    if not parts:
        return False
    # ① 目录段命中测试根（不看最后一段——那是文件名）
    for seg in parts[:-1]:
        if seg in _AUDIT_TEST_DIRS:
            return True
    name = parts[-1]
    # ② 前缀：test_ 全仓；探针组只认 tools/ 父目录，或根级单文件名
    if _audit_prefixed(name, _AUDIT_TEST_PREFIX_ANY):
        return True
    if (len(parts) > 1 and parts[-2] == "tools") or len(parts) == 1:
        if _audit_prefixed(name, _AUDIT_TEST_PREFIX_TOOLS):
            return True
    # ③ 后缀（命名契约，全仓）
    return name.endswith(_AUDIT_TEST_SUFFIX)

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
    - NotebookEdit：new_source（cell 新内容）行数；delete 无内容变更计 0。
    - 纯文档豁免：审计线管的是程序风险，.md/.txt 等不会被执行的纯文档
      不计行数（README 大改不该逼出 designer/reviewer）；口径按后缀——
      .md .mdx .txt .rst .adoc .markdown，file_path 取不到不豁免。"""
    try:
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        if path.lower().endswith(_AUDIT_DOC_EXTS):
            return 0
        if _audit_is_test_path(path):
            return 0
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


# v3.5.42（用户拍板回退 v3.5.40）：Bash 写文件计数退役——审计只统计
# Edit/Write/MultiEdit/NotebookEdit 四个直改工具（用户口径：只统计
# edit 这类；Bash 的用途远不止写文件，按命令猜写文件行为误伤面大）。
# _audit_bash_lines/_BASH_WRITE_RE 随退役删除。

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
    audit_hook.py）。双形态命令与 _ask_mcp_cfg_path 同构：源码=
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
