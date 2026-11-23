# -*- coding: utf-8 -*-
"""harness 包 —— v3.0 自 src/claude_harness.py 重构拆分。

旧引用入口 src/claude_harness.py 兼容 shim 已随 B 激进批退役（a140），
一律 from src.harness.xxx import ...。各模块职责见各自 docstring。
"""
# harness 版本单一源（v3.5.0+ 用户拍板「与工具版本分离」——harness 迭代
# 快于发版，独立演进号）：GET /api/harness/version 下发，前端 index.html
# 静态值仅作首屏兜底。与工具发版版本 src.version.APP_VERSION 互不牵连
#（打包/升级链只看 APP_VERSION）。
#
# a467：常量手工 bump 在 a388 之后 80 个提交里一次都没发生（用户实锤：
# 诊断栏一直 v4.1.0-a405——运行实例更旧）。改为**启动时从 git 提交史自动
# 取最新 v4.1.0-aNNN**（源码运行机器都有 git）；打包版无 .git 回落常量
#（发版打包时以当时 HEAD 为准改一次即可）。进程内缓存——版本反映的是
# **正在运行的代码**，提交后不重启不换号（与「请重启生效」横幅语义一致）。
_HARNESS_FALLBACK = "4.1.0-a685"   # 仅最后兜底：打包形态读 build 盖章(见_git_harness_version)


def _parse_harness_version(subjects):
    """从提交标题（新→旧）取第一个 v4.1.0-aNNN。纯函数供测试。"""
    import re
    for s in subjects or []:
        m = re.match(r"^v4\.1\.0-a(\d+)", str(s or ""))
        if m:
            return "4.1.0-a" + m.group(1)
    return ""


def _repo_head_sig(root):
    """快速读仓库 HEAD 指纹（纯文件读，零子进程）：'ref:sha' / 'detached:sha'。
    读不到（packed-refs 等异常形态）返回空 → 调用方走同步 git 慢路径。"""
    import os
    try:
        with open(os.path.join(root, ".git", "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        if not head:
            return ""
        if head.startswith("ref:"):
            ref = head[4:].strip()
            p = os.path.join(root, ".git", ref.replace("/", os.sep))
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return ref + ":" + f.read().strip()
            return ""                  # packed-refs 形态：放弃快速路径
        return "detached:" + head
    except Exception:
        return ""


def _version_cache_path():
    import os
    from src import app_state as _st
    return os.path.join(_st.STATE_DIR, "harness_version.cache")


def _read_version_cache():
    try:
        with open(_version_cache_path(), encoding="utf-8") as f:
            sig = f.readline().strip()
            ver = f.readline().strip()
        return (sig, ver) if sig and ver else ("", "")
    except Exception:
        return ("", "")


def _write_version_cache(sig, ver):
    try:
        import os
        p = _version_cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(sig + "\n" + ver + "\n")
        os.replace(tmp, p)             # 原子替换：并发 worker/测试实例互不撕裂
    except Exception:
        pass


def _git_version_sync(root):
    """同步跑 git 取版本串（慢路径，仅 HEAD 指纹变化/缓存缺失时）。"""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "log", "--format=%s", "-n", "400"],
            cwd=root, capture_output=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        ver = _parse_harness_version(
            out.decode("utf-8", "replace").splitlines())
        # a650（用户实锤「刷新了没修好」）：版本串只认主题里的 aNNN——
        # 无号提交（分支修复/实验批）不 bump 版本 → ?v= 不变 → WebView
        # 命中旧缓存，「改了没效果」连环坑复活。附 HEAD 短哈希：任何提交
        # （含无号分支提交）都自动破缓存；- 分隔（+ 在 query 里会被解码
        # 成空格）
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        h = head.decode("utf-8", "replace").strip()
        if h:
            return (ver + "-" + h) if ver else h
        return ver
    except Exception:
        return ""


def _git_harness_version():
    """git 提交史取版本；无 git/无 .git/任何异常返回空（走回落）。

    启动性能（用户实锤「启动还是慢」）：pythonw 冷启动下 git 子进程可达
    秒级（main.py 终审 P2-5 注释同款实锤），而版本号只是显示串/?v= 破缓存
    参数。改为「HEAD 指纹缓存优先」——纯文件读（µs 级）比对上次记录：
      · 指纹一致（仓库没提交/拉取过）→ 直接用缓存版本串，零子进程；
      · 指纹不一致/缓存缺失 → 同步跑 git 并刷新缓存（每次仓库变化只付一次）。
    正确性：git log 主题史是 HEAD sha 的函数——sha 不变历史必不变。
    打包版读 build.py 盖的版本章；章也缺才落回落常量。"""
    import os
    import sys
    d = os.path.dirname(os.path.abspath(__file__))

    def _read_stamp():
        """读打包时 build.py 盖的版本章（_internal/harness_version.txt，与
        源码 git 推导同格式）。取不到返回空（走回落常量）。"""
        try:
            # utf-8-sig：本仓库编辑链会产出带 BOM 的文件（version.py/
            # installer.nsh 皆然）——若章被带 BOM 保存，裸 utf-8 会把
            # \ufeff 读进版本串（?v= 参数与显示都带脏字符）。-sig 两种都吃
            with open(os.path.join(getattr(sys, "_MEIPASS", ""),
                                   "harness_version.txt"),
                      encoding="utf-8-sig") as f:
                return f.readline().strip()
        except Exception:
            return ""

    if getattr(sys, "frozen", False):
        # 第三轮 M3：frozen 不做 .git 上溯——安装/调试目录若恰落在任一
        # git 工作树 ≤6 层内，会被无关仓库劫持版本推导（绕过盖章）。
        # 注意必须**先读章再返回**：早先的写法是裸 return ""，把读章一起
        # 绕过了，frozen 直接落兜底常量（第四轮自审实锤，已修）。
        return _read_stamp()
    for _ in range(6):                    # src/harness → 仓库根
        if os.path.isdir(os.path.join(d, ".git")):
            break
        d = os.path.dirname(d)
    else:
        # 源码树内但找不到仓库根（嵌套解压等）：同样读章兜底
        return _read_stamp()
    sig = _repo_head_sig(d)
    if sig:
        csig, cver = _read_version_cache()
        if csig == sig and cver:
            return cver                   # 快路径：仓库自上次启动未变
    ver = _git_version_sync(d)
    if ver and sig:
        _write_version_cache(sig, ver)
    return ver


HARNESS_VERSION = _git_harness_version() or _HARNESS_FALLBACK
from .consts import (_EVENTS_MAX, _IDLE_KILL_S, _META_FILE, _PROMPTS_KEY, _PROMPTS_LEGACY_KEY, _QUEUE_MAX, _SKILL_ZH_FILE, _SRC_DIR, _UPLOAD_DIR, _UPLOAD_MAX, _sessions, _sessions_lock, log)
from .meta import (_meta, _meta_load, _meta_loaded, _meta_lock, _meta_save, _meta_tombstones, log)
from .models import (_models_cache, available_models, log)
from .prompts import (_collect_system_prompt, _prompt_matches_project, _prompts_load, _prompts_save, log)
from .bridges import (TOKEN_RULES, _bridge_fp, ask_bridge_text, confirm_bridge_text, log, vision_bridge_text)
from .askmcp import (_ask_mcp_cfg_path, log)
from .audit import (_AUDIT_EDIT_TOOLS, _AUDIT_LOG_MAX, _AUDIT_MSG_PREFIX, _AUDIT_ROLES, _audit_dispatch_role, _audit_hook_settings_path, _audit_iso_now, _audit_lines, _audit_log_append, _audit_log_read, _audit_nlines, log)
from .session import (HarnessSession, _CTX_WINDOW_1M, _CTX_WINDOW_DEFAULT, _session_ctx_used, _session_ctx_window, log)
from .transcript import (_SKIP_RE, _SUBAGENT_BLK_FULL, _extract_att, _inject_subagent_blocks, _map_subagent_rows, _strip_att, _subagent_rows_for, _subagent_rows_from_jsonl, _subagent_transcript_candidates, _tool_summary, log, re_title, transcript_for)
