# -*- coding: utf-8 -*-
"""版本控制 API（Flask Blueprint）——git / svn 工作副本查看与常用写操作。

范围（用户拍板）：只读查看（类型识别/分支修订/改动列表/单文件 diff/最近
提交）+ 常用写（add / commit 自填说明 / git pull --ff-only / svn update）。
明确不含 push、还原/丢弃改动、冲突解决——分叉/冲突时干净失败并引导去
命令行，绝不留半合并态。

安全模型（沿 file_tree.py 根目录登记制）：所有路径必须落在文件树已登记
根的子树内（_under_roots 门卫）；仓库根解析出登记根之外 → 拒绝并引导。
argv 一律 list（无 shell 拼接）；git 路径参数带 `--` 分隔符。

编码：git 输出 UTF-8（-c core.quotepath=false）→ GBK（svn 人类可读输出在
中文 Windows 是 ACP）→ utf-8 replace 三跳；svn 结构化数据走 --xml（恒
UTF-8）从根上免猜。subprocess 禁 text=True（默认按 locale 解，跨机不稳）。
"""
import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from src import app_state as _st
from src.file_tree import _under_roots

vcs_bp = Blueprint("vcs", __name__)

CREATE_NO_WINDOW = 0x08000000
VCS_TIMEOUT_RO = 20
# v3.5.264（SVN三问题报告 Q1）：全树 status 移出 status 端点关键路径——
# 网络盘大仓库（SMB+内核树）实测 54s+，独立 changes 端点配长超时 ≥90s
VCS_TIMEOUT_CHG = 90     # status/log/diff/show/cat
VCS_TIMEOUT_RW = 60     # add/commit
VCS_TIMEOUT_NET = 120   # pull/update
FILES_CAP = 500         # 改动列表上限（对齐 file_tree LIST_CAP 文化）
_LOG_CAP = 500         # v2：单次 log 上限（翻页/回补一次拿够）
_SKIP_CAP = 5000       # v2：skip+limit 累积深度上限（巨仓深翻脚注引导命令行）
_TMP_KEEP_S = 24 * 3600
_TMP_MAX = 60

_ROOT_LOCKS = {}
_ROOT_LOCKS_GUARD = threading.Lock()


def _root_lock(wc_dir):
    """每个工作副本一把写锁——同仓 commit/update 串行，跨仓互不阻塞。
    键 normcase 归一（轻审 P9：Windows 同仓异形态防两把锁）。"""
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(os.path.normcase(wc_dir), threading.Lock())


def _data_dir():
    """运行时取 app_state.DATA_DIR（v3.5.118，轻审 P4：from-import 是值
    拷贝，数据目录迁移端点回写 _st.DATA_DIR 后这里仍指旧目录——vcs_tmp
    会落已删除的旧位置并复活目录。函数内查 _st 属性根治，测试同受益）。"""
    d = _st.DATA_DIR
    os.makedirs(d, exist_ok=True)
    return d


def _dec(b):
    """命令输出解码三跳：utf-8 严格 → GBK 严格 → utf-8 replace。"""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return b.decode("utf-8", "replace")


def _run(argv, cwd, timeout):
    """subprocess 统一入口：list argv / bytes 输出 / 隐藏窗口 / 超时保护。
    返回 (rc, out_str, err_str)——超时转 rc=-1 + err 文案。"""
    try:
        # B组P7：git/svn 子进程强制 C locale——shortstat 解析按英文
        # 「N insertions/deletions」配对，zh_CN gettext 下徽章会整体消失
        import subprocess as _sp
        _env = dict(os.environ, LC_ALL="C", LANG="C")
        p = subprocess.run([str(a) for a in argv], cwd=cwd,
                           capture_output=True, timeout=timeout,
                           env=_env, creationflags=CREATE_NO_WINDOW)
        return p.returncode, _dec(p.stdout), _dec(p.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时（%ds）——仓库过大或命令行假死" % timeout
    except FileNotFoundError:
        return -1, "", "命令不存在"
    except Exception as e:
        return -1, "", str(e)


def _tool(name):
    """CLI 探测：None = 未安装（调用方呈现「未安装」占位，绝不抛错）。"""
    return shutil.which(name)


def _tmp_materialize(data, name_hint):
    """把旧版本字节物化成临时文件，供 buildDiffViewerTab 走真实路径打开。
    命名 <sha1 短前缀>_<hint>；顺带清理 >24h 或总数 >60 的旧件。"""
    d = os.path.join(_data_dir(), "vcs_tmp")
    os.makedirs(d, exist_ok=True)
    now = time.time()
    try:
        olds = sorted((os.path.join(d, f) for f in os.listdir(d)),
                      key=lambda p: os.path.getmtime(p))
        stale = [p for p in olds if now - os.path.getmtime(p) > _TMP_KEEP_S]
        for p in stale:
            try:
                os.remove(p)
            except OSError:
                pass
        keep = [p for p in olds if p not in stale]
        for p in keep[:max(0, len(keep) - _TMP_MAX)]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
    h = hashlib.sha1(data).hexdigest()[:10] if data else "empty"
    safe = re.sub(r"[^0-9A-Za-z._@\[\]-]", "_", name_hint or "file")
    path = os.path.join(d, "%s_%s" % (h, safe))
    with open(path, "wb") as f:
        f.write(data)
    return path


def _wc_root(path):
    """解析 path 所属工作副本。返回 (vcs, wc_dir, err)：
    - vcs ∈ {'git','svn'}，wc_dir 为仓库根绝对路径（登记根子树内）
    - vcs=None：err 带原因（不在登记根内 / 非版本控制目录 / 仓库根越界）"""
    p = _under_roots(path)
    if not p:
        return None, None, "路径不在文件树已登记目录内——请先在左侧文件树打开该工程目录"
    cur = p
    for _ in range(8):                      # 向上最多 8 跳找标记
        if os.path.exists(os.path.join(cur, ".git")):
            return "git", cur, None
        if os.path.isdir(os.path.join(cur, ".svn")):
            return "svn", cur, None
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # 目录树标记没找到（如 bare 布局/极深嵌套）再借命令确认一次
    for vcs, argv in (("git", ["git", "rev-parse", "--show-toplevel"]),
                      ("svn", ["svn", "info", "--xml", p])):
        if _tool(vcs):
            rc, out, _e = _run(argv, p, VCS_TIMEOUT_RO)
            if rc == 0:
                if vcs == "git":
                    cand = out.strip().splitlines()[0].strip() if out.strip() else None
                else:
                    m = re.search(r"<wcroot-abspath>(.+?)</wcroot-abspath>", out)
                    cand = m.group(1).strip() if m else None
                if cand:
                    cand = os.path.abspath(cand)
                    if _under_roots(cand) and (
                            cand == _under_roots(cand) or
                            cand.startswith(_under_roots(cand) + os.sep)):
                        if os.path.exists(os.path.join(cand, ".git")):
                            return "git", cand, None
                        if os.path.isdir(os.path.join(cand, ".svn")):
                            return "svn", cand, None
                    return None, None, "仓库根（%s）在文件树登记根之外——请把仓库根目录加入左侧文件树" % cand
    return None, None, "该目录不是 git / svn 工作副本"


def _guard(root, need_tool=None):
    """公共前置：解析工作副本 + 工具探测。返回 (vcs, wc, err_resp, tool)。
    err_resp 非 None 时调用方直接返回它。"""
    vcs, wc, err = _wc_root(root)
    if err:
        return None, None, (jsonify({"ok": False, "err": err}), 400), None
    tool = bool(_tool(vcs))
    if need_tool and not tool:
        return (None, None,
                (jsonify({"ok": False,
                          "err": "%s 客户端未安装——安装 %s 命令行并重启后可用"
                                 % (vcs, vcs)}), 400), False)
    return vcs, wc, None, tool


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

_GIT_ST_MAP = {"M": "M", "A": "A", "D": "D", "R": "R", "C": "C", "?": "?", "!": "!"}


def _git_status(wc):
    rc, out, err = _run(["git", "-c", "core.quotepath=false",
                         "status", "--porcelain=v1", "-z", "--branch"],
                        wc, VCS_TIMEOUT_RO)
    if rc != 0:
        return None, err or "git status 失败"
    branch, ahead, behind = "", 0, 0
    files = []
    toks = out.split("\0")
    it = iter(toks)
    for tok in it:
        if not tok:
            continue
        if tok.startswith("## "):
            head = tok[3:]
            m = re.match(r"(\S+?)\.\.\.\S+\s*\[(?:ahead (\d+))?[,\s]*(?:behind (\d+))?\]",
                         head)
            if m:
                branch = m.group(1)
                ahead, behind = int(m.group(2) or 0), int(m.group(3) or 0)
            elif head.startswith("No commits"):
                branch = re.sub(r"^No commits yet on ", "", head)
            else:
                branch = head.split("...")[0].strip() or head
            continue
        xy = tok[:2]
        st = _GIT_ST_MAP.get(xy[0] if xy[0] not in " M" else
                             (xy[1] if xy[1] != " " else xy[0]), "?")
        # v3.5.118（轻审 P5）：unmerged（UU/AU/DD 等）→ C 冲突态，绝不显示成
        # 「未纳管」给 ＋add 按钮（git add 强收冲突是破坏性误导）
        if "U" in xy:
            st = "C"
        rel = tok[3:]
        if xy[0] in "RC":                   # rename/copy: new\0old（轻审 P7：C 同消费）
            old_rel = next(it, "")
            files.append({"rel": rel.replace("\\", "/"), "path": rel,
                          "st": st, "old_rel": old_rel.replace("\\", "/")})
        else:
            files.append({"rel": rel.replace("\\", "/"), "path": rel, "st": st})
    rc, rev, _e = _run(["git", "rev-parse", "--short", "HEAD"], wc, 10)
    truncated = max(0, len(files) - FILES_CAP)
    return {"vcs": "git", "tool": True, "branch": branch, "rev": rev.strip(),
            "ahead": ahead, "behind": behind,
            "files": files[:FILES_CAP], "truncated": truncated}, None


def _svn_info(wc):
    """v3.5.264（Q1 主修）：O(1) svn info——rev/branch 0.3s 级，status 端点
    只跑这个（全树 status 移出关键路径，见 /api/vcs/changes）。"""
    rc, out, err = _run(["svn", "info", "--xml"], wc, VCS_TIMEOUT_RO)
    rev, branch = "", ""
    if rc == 0:
        try:
            root = ET.fromstring(out.encode("utf-8"))
            e = root.find("entry")
            if e is not None:
                c = e.find("commit")
                rev = (c.get("revision") if c is not None else "") or ""
                u = e.findtext("url") or ""
                branch = u.rstrip("/").rsplit("/", 1)[-1]
        except ET.ParseError:
            pass
    return rev, branch


def _svn_changes(wc, depth=None):
    """v3.5.264（Q1 主修）：svn status 独立函数——配长超时，由
    /api/vcs/changes 单独调用（前端惰性加载），不再阻塞 status。
    v3.5.272b（报告 §6 分层加载）：depth='empty' 顶层模式（--depth empty
    实测 0.45s vs 全树 39~54s）——首屏秒出顶层改动，全树由前端二段补扫
    覆盖；超时 30s 对秒级余量充足。"""
    argv = ["svn", "status", "--xml"]
    if depth:
        argv += ["--depth", depth]
    rc, out, err = _run(argv, wc, 30 if depth == "empty" else VCS_TIMEOUT_CHG)
    if rc != 0:
        if "超时" in (err or ""):
            return {"files": [], "truncated": 0,
                    "changes_timeout": True, "shallow": bool(depth)}, None
        return None, err or "svn status 失败"
    files = []
    try:
        root = ET.fromstring(out.encode("utf-8"))
        for t in root.iter("target"):
            for e in t.iter("entry"):
                rel = e.get("path", "").replace("\\", "/")
                if not rel:
                    continue
                it = e.find("wc-status")
                if it is None:
                    continue
                st_raw = it.get("item", "none")
                st = {"modified": "M", "added": "A", "deleted": "D",
                      "unversioned": "?", "conflicted": "C",
                      "replaced": "R", "missing": "!", "none": ""}.get(st_raw)
                if not st:
                    continue
                old = (it.findtext("move-to") or "")
                files.append({"rel": rel, "path": rel, "st": st,
                              **({"old_rel": old} if old else {})})
    except ET.ParseError as e:
        return None, "svn status 输出解析失败：%s" % e
    truncated = max(0, len(files) - FILES_CAP)
    return {"files": files[:FILES_CAP], "truncated": truncated,
            "shallow": bool(depth)}, None


def _svn_status(wc):
    """v3.5.267（全审收编）：组合 _svn_info + _svn_changes——原实现与
    _svn_changes 整段重复（解析块两份）。生产零调用者（status 端点已拆轻
    路径），保留仅为 tests/test_vcs.py 旧语义兼容。"""
    rev, branch = _svn_info(wc)
    chg, e = _svn_changes(wc)
    if e:
        return None, e
    d = {"vcs": "svn", "tool": True, "branch": branch, "rev": rev,
         "ahead": 0, "behind": 0}
    d.update(chg or {"files": [], "truncated": 0, "changes_timeout": True})
    return d, None


@vcs_bp.route("/api/vcs/status", methods=["POST"])
def vcs_status():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    # v3.5.118（轻审 P3）：「未安装 = tool:False 占位」设计内首态——status 是
    # 只读探测，未装 CLI 时返回 200 + 空 files，前端渲染占位而非报错
    if not _tool(vcs):
        return jsonify({"ok": True, "vcs": vcs, "tool": False, "branch": "",
                        "rev": "", "ahead": 0, "behind": 0,
                        "files": [], "truncated": 0})
    # v3.5.264（Q1）：svn 走轻路径——只 svn info（0.3s 级），全树 status 移
    # 出关键路径（/api/vcs/changes 惰性加载）；files 空表+changes_pending 标
    # 记，前端显示「改动扫描中」占位。git 的 status 本身亚秒级，维持原样
    if vcs == "svn":
        rev, branch = _svn_info(wc)
        return jsonify({"ok": True, "vcs": "svn", "tool": True,
                        "branch": branch, "rev": rev, "ahead": 0, "behind": 0,
                        "files": [], "truncated": 0, "changes_pending": True})
    res, e = _git_status(wc)
    if e:
        return jsonify({"ok": False, "err": e}), 500
    return jsonify({"ok": True, **res})


@vcs_bp.route("/api/vcs/changes", methods=["POST"])
def vcs_changes():
    """v3.5.264（Q1）：改动列表独立端点——svn 全树 status（长超时 90s）/
    git 复用 _git_status。前端版本 tab 激活/手动⟳/写操作后惰性调用，
    不再拖垮 status 关键路径与 logbtn。"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    if not _tool(vcs):
        return jsonify({"ok": True, "vcs": vcs, "tool": False,
                        "files": [], "truncated": 0})
    if vcs == "svn":
        # v3.5.275（对抗审 F1）：端点接线——272 首笔 vcs.py 未进提交、272b
        # 只补了函数体，端点从未透传 shallow（分层加载端到端失效实锤）。
        # shallow=1 → depth='empty' 顶层模式（--depth empty 秒级）
        res, e = _svn_changes(wc, depth="empty" if data.get("shallow") else None)
        if e:
            return jsonify({"ok": False, "err": e}), 500
        return jsonify({"ok": True, "vcs": "svn", **res})
    res, e = _git_status(wc)
    if e:
        return jsonify({"ok": False, "err": e}), 500
    return jsonify({"ok": True, "vcs": "git",
                    "files": res.get("files", []),
                    "truncated": res.get("truncated", 0)})


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

# ---- v2（designer 方案 S1）：log 查询计划——参数校验+命令组装纯函数 ----

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
# git --author 是 BRE 正则——仅转义这 6 个元字符（GNU BRE 里转义 +?(){}| 反而
# 制造元字符，切不可用 re.escape，designer D10）
_BRE_META = "\\.*[]^$"


def _bre_lit(s):
    return "".join(("\\" + c) if c in _BRE_META else c for c in s)


def _log_plan(vcs, data):
    """校验并组装 log 查询。返回 (err_tuple|None, git_argv|None,
    git_count_argv|None, svn_argv|None, skip, limit)。"""
    try:
        limit = max(1, min(_LOG_CAP, int(data.get("limit") or 30)))
    except (TypeError, ValueError):
        limit = 30
    try:
        skip = max(0, int(data.get("skip") or 0))
    except (TypeError, ValueError):
        skip = 0
    if skip + limit > _SKIP_CAP:
        return (("深度超限：skip+limit ≤ %d（更早历史请用命令行）" % _SKIP_CAP), 400), \
            None, None, None, skip, limit
    text = _CTRL_RE.sub("", str(data.get("text") or "").strip())[:200]
    author = _CTRL_RE.sub("", str(data.get("author") or "").strip())[:200]
    since = str(data.get("since") or "").strip()
    until = str(data.get("until") or "").strip()
    for d in (since, until):
        if d and not _DATE_RE.match(d):
            return (("日期格式应为 YYYY-MM-DD"), 400), None, None, None, skip, limit
        if d:
            # 全审L3：正则之外补语义校验——2026-13-45 这类正则可过、git 静默
            # 返回空的假日期在此真拒
            try:
                import datetime as _dt
                _dt.date(*[int(x) for x in d.split("-")])
            except ValueError:
                return (("日期无效：%s" % d), 400), None, None, None, skip, limit
    if since and until and since > until:
        return (("起始日期不能晚于结束日期"), 400), None, None, None, skip, limit
    before_rev = str(data.get("before_rev") or "").strip()

    if vcs == "git":
        argv = ["git", "log", "-n", str(limit), "--date=iso-strict",
                "--decorate=short", "--shortstat",
                "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1f%d"]
        cargv = ["git", "rev-list", "--count", "HEAD"]
        if skip:
            argv += ["--skip", str(skip)]
        if text:
            argv += ["--fixed-strings", "-i", "--all-match"]
            for w in text.split():
                argv += ["--grep", w]
            cargv += ["--fixed-strings", "-i", "--all-match"]
            for w in text.split():
                cargv += ["--grep", w]
        if author:
            argv += ["--author", _bre_lit(author)]
            cargv += ["--author", _bre_lit(author)]
        if since:
            argv += ["--since", since + "T00:00:00"]
            cargv += ["--since", since + "T00:00:00"]
        if until:
            argv += ["--until", until + "T23:59:59"]
            cargv += ["--until", until + "T23:59:59"]
        return None, argv, (None if skip else cargv), None, skip, limit

    # svn：-r 游标/日期花括号 + --search（1.8+，整串 OR 语义，与 git AND 差异
    # 由前端 placeholder 文档化）；作者无等价参数（不显示控件，designer D10）
    argv = ["svn", "log", "--xml"]
    lo = "{%s}" % (since + "T00:00:00") if since else "1"
    hi = "{%s}" % (until + "T23:59:59") if until else "HEAD"
    if before_rev:
        if not before_rev.isdigit():
            return (("svn 游标必须是数字修订号"), 400), None, None, None, skip, limit
        argv += ["-r", "%s:%s" % (before_rev, lo)]
    else:
        argv += ["-r", "%s:%s" % (hi, lo)]
    argv += ["-l", str(limit)]
    if text:
        argv += ["--search", text]
    return None, None, None, argv, skip, limit


@vcs_bp.route("/api/vcs/log", methods=["POST"])
def vcs_log():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    plan = _log_plan(vcs, data)
    err_t, git_argv, git_count_argv, svn_argv, skip, limit = plan
    if err_t:
        return jsonify({"ok": False, "err": err_t[0]}), err_t[1]
    commits = []
    total = None
    if vcs == "git":
        rc, out, e = _run(git_argv, wc, VCS_TIMEOUT_RO)
        if rc != 0:
            if "does not have any commits yet" in (e or "") or rc == 128 and not out:
                return jsonify({"ok": True, "commits": []})
            return jsonify({"ok": False, "err": e or "git log 失败"}), 500
        for line in out.splitlines():
            parts = line.split("\x1f")
            # v2 D9：5 字段放宽为 ≥5（第 6 可选 deco，带前导空格须 trim）
            if len(parts) >= 5:
                commits.append({"rev": parts[0], "short": parts[1],
                                "author": parts[2], "date": parts[3],
                                "msg": parts[4],
                                "deco": (parts[5].strip() if len(parts) > 5 else "")})
            elif commits and " changed" in line:
                # v3.5.198（用户需求「提交列表加增减数字」）：--shortstat 追加行
                # 「 N files changed, N insertions(+), N deletions(-)」配对上一条
                _mi = re.search(r"(\d+) insertion", line)
                _md = re.search(r"(\d+) deletion", line)
                commits[-1]["ins"] = int(_mi.group(1)) if _mi else 0
                commits[-1]["del"] = int(_md.group(1)) if _md else 0
        if git_count_argv:   # 仅首页（skip==0）附带精确总数（svn 无此能力）
            rc2, out2, _e2 = _run(git_count_argv, wc, VCS_TIMEOUT_RO)
            if rc2 == 0:
                try:
                    total = int(out2.strip() or 0) or None
                except ValueError:
                    total = None
    else:
        rc, out, e = _run(svn_argv, wc, VCS_TIMEOUT_RO)
        if rc != 0 and "--search" in svn_argv and (
                "invalid option" in (e or "") or "unknown option" in (e or "")):
            # svn <1.8 无 --search：APR getopt 实证 stderr 是「svn: invalid
            # option: --search」（unknown option 是 git 措辞——P1 修）；去掉
            # 重拉，客户端过滤由前端按 banner 提示处理已载分页
            _argv2 = list(svn_argv)
            _i = _argv2.index("--search")
            del _argv2[_i:_i + 2]
            rc, out, e = _run(_argv2, wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "svn log 失败"}), 500
        try:
            root = ET.fromstring(out.encode("utf-8"))
            for le in root.iter("logentry"):
                commits.append({"rev": le.get("revision", ""),
                                "short": "r%s" % le.get("revision", ""),
                                "author": le.findtext("author") or "",
                                "date": le.findtext("date") or "",
                                "msg": (le.findtext("msg") or "").strip(),
                                "deco": ""})
        except ET.ParseError as pe:
            return jsonify({"ok": False, "err": "svn log 解析失败：%s" % pe}), 500
    resp = {"ok": True, "commits": commits}
    if total is not None:
        resp["total"] = total
    return jsonify(resp)


# ---------------------------------------------------------------------------
# diff（旧版本物化成临时文件，前端 buildDiffViewerTab 走真实路径）
# ---------------------------------------------------------------------------

def _git_old_bytes(wc, rel, st):
    if st == "A":                           # 新增文件：旧版为空
        return b""
    try:                                    # 轻审 P6：超时/异常降级空旧版
        p = subprocess.run(["git", "show", "HEAD:%s" % rel], cwd=wc,
                           capture_output=True, timeout=VCS_TIMEOUT_RO,
                           creationflags=CREATE_NO_WINDOW)
        return p.stdout if p.returncode == 0 else b""
    except Exception:
        return b""


def _svn_old_bytes(wc, rel, st):
    if st == "A":
        return b""
    try:
        p = subprocess.run(["svn", "cat", "-r", "BASE", os.path.join(wc, rel)],
                           cwd=wc, capture_output=True, timeout=VCS_TIMEOUT_RO,
                           creationflags=CREATE_NO_WINDOW)
        return p.stdout if p.returncode == 0 else b""
    except Exception:
        return b""


@vcs_bp.route("/api/vcs/commit_files", methods=["POST"])
def vcs_commit_files():
    """v3.5.131：点「最近提交」行查看该提交的改动文件清单（用户需求
    「历史提交点开查看历史修改情况」）。git：show --name-status；svn：
    diff --summarize -c rev。rev 走 _run 原样传参（无 shell 注入面）。"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    rev = str(data.get("rev") or "").strip()
    if not rev or len(rev) > 64 or not re.match(r"^[0-9a-zA-Z^-]{1,64}$", rev):
        return jsonify({"ok": False, "err": "非法修订号"}), 400
    if vcs == "svn" and not rev.isdigit():
        return jsonify({"ok": False, "err": "svn 修订号必须是数字"}), 400
    files = []
    if vcs == "git":
        # v3.5.132（轻审严重2）：quotepath=false——非 ASCII 文件名默认输出
        # 引号+八进制转义，下游 git show rev:path 实测 fatal 假无差异
        rc, out, e = _run(["git", "-c", "core.quotepath=false", "show",
                           "--name-status", "--no-renames",
                           "--format=", rev], wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "git show 失败"}), 500
        for line in out.splitlines():
            m = re.match(r"^([AMD])\t(.+)$", line)
            if m:
                files.append({"st": m.group(1), "path": m.group(2)})
    else:
        rc, out, e = _run(["svn", "diff", "--summarize", "-c", rev, wc],
                          wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "svn diff 失败"}), 500
        wcp = wc.replace("/", os.sep).rstrip(os.sep) + os.sep
        for line in out.splitlines():
            # v3.5.132（轻审严重1）：双捕获组——旧单组取路径首字符当状态字母
            m = re.match(r"^([AMD])\s+(.+)$", line.strip())
            if not m:
                continue
            path = m.group(2).replace("\\", "/")
            apath = path.replace("/", os.sep)
            if apath.startswith(wcp):   # svn summarize 可能输出绝对路径——剥工作副本前缀转 rel
                path = apath[len(wcp):].replace(os.sep, "/")
            files.append({"st": m.group(1), "path": path})
    return jsonify({"ok": True, "files": files[:200]})


@vcs_bp.route("/api/vcs/commit_diff", methods=["POST"])
def vcs_commit_diff():
    """v3.5.131：单文件在某提交的改动对比——父修订/该修订两版物化临时文件，
    前端 buildDiffViewerTab 走真实路径（与 /api/vcs/diff 同机制）。"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    rev = str(data.get("rev") or "").strip()
    if not rev or len(rev) > 64 or not re.match(r"^[0-9a-zA-Z^-]{1,64}$", rev):
        return jsonify({"ok": False, "err": "非法修订号"}), 400
    # v3.5.132（轻审一般3）：svn 分支要算 rev-1——非数字提前 400（int() 异常
    # 会裸 500 HTML）
    if vcs == "svn" and not rev.isdigit():
        return jsonify({"ok": False, "err": "svn 修订号必须是数字"}), 400
    rel = str(data.get("path") or "").replace("\\", "/").strip()
    if _bad_rel(rel):
        return jsonify({"ok": False, "err": "非法文件路径"}), 400
    st = str(data.get("st") or "M")

    def _git_rev_bytes(spec):
        try:
            # v3.5.132（轻审严重2）：quotepath 同步——rel 含非 ASCII 时 rev:rel
            # 必须按原字节名寻址
            p = subprocess.run(["git", "-c", "core.quotepath=false", "show",
                                "%s:%s" % (spec, rel)], cwd=wc,
                               capture_output=True, timeout=VCS_TIMEOUT_RO,
                               creationflags=CREATE_NO_WINDOW)
            return p.stdout if p.returncode == 0 else b""
        except Exception:
            return b""

    base = os.path.basename(rel)
    if vcs == "git":
        a_bytes = b"" if st == "A" else _git_rev_bytes(rev + "~1")
        b_bytes = b"" if st == "D" else _git_rev_bytes(rev)
        a_hint, b_hint = "%s@%s~1" % (base, rev[:8]), "%s@%s" % (base, rev[:8])
    else:
        def _svn_rev_bytes(r):
            try:
                p = subprocess.run(["svn", "cat", "-r", r, os.path.join(wc, rel)],
                                   cwd=wc, capture_output=True, timeout=VCS_TIMEOUT_RO,
                                   creationflags=CREATE_NO_WINDOW)
                return p.stdout if p.returncode == 0 else b""
            except Exception:
                return b""
        a_bytes = b"" if st == "A" else _svn_rev_bytes(str(int(rev) - 1))
        b_bytes = b"" if st == "D" else _svn_rev_bytes(rev)
        a_hint, b_hint = "%s@r%s-1" % (base, rev), "%s@r%s" % (base, rev)
    return jsonify({"ok": True, "a": _tmp_materialize(a_bytes, a_hint),
                    "b": _tmp_materialize(b_bytes, b_hint)})


@vcs_bp.route("/api/vcs/diff", methods=["POST"])
def vcs_diff():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    rel = str(data.get("path") or "").replace("\\", "/").strip()
    if _bad_rel(rel):
        return jsonify({"ok": False, "err": "非法文件路径"}), 400
    full = os.path.join(wc, *rel.split("/"))
    st = str(data.get("st") or "M")
    if vcs == "git":
        a_bytes = _git_old_bytes(wc, rel, st)
    else:
        a_bytes = _svn_old_bytes(wc, rel, st)
    try:
        b_bytes = open(full, "rb").read() if os.path.isfile(full) else b""
    except OSError:
        b_bytes = b""
    a_hint, b_hint = "%s@%s" % (os.path.basename(rel),
                                "HEAD" if vcs == "git" else "BASE"), os.path.basename(rel)
    return jsonify({"ok": True, "a": _tmp_materialize(a_bytes, a_hint),
                    "b": _tmp_materialize(b_bytes, b_hint)})


# ---------------------------------------------------------------------------
# 写操作：add / commit / update（per-root 锁 + 显式确认语义）
# ---------------------------------------------------------------------------

def _bad_rel(p):
    """rel 路径统一校验（轻审 P2）：空 / 绝对（/ 或盘符）/ .. 穿越全拒。"""
    p = (p or "").replace("\\", "/").strip()
    return (not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p)
            or ".." in p.split("/"))


def _git_add_missing(wc, paths):
    """勾选中未跟踪的先 add（git 提交 pathspec 限定时未跟踪文件必须先入索引）。
    v3.5.118（轻审 P1 严重）：porcelain -z 的 untracked token 是 "?? path"
    （两个问号+空格）——旧代码 startswith("? ")+tok[2:] 永假，新文件从不
    自动 add，git commit 原子失败连坐同组已跟踪文件。"""
    rc, out, _e = _run(["git", "-c", "core.quotepath=false",
                        "status", "--porcelain=v1", "-z"], wc, VCS_TIMEOUT_RO)
    if rc != 0:
        return
    untracked = set()
    toks = out.split("\0")
    it = iter(toks)
    for tok in it:
        if tok.startswith("?? "):
            untracked.add(tok[3:].replace("\\", "/"))
        elif tok[:2] in ("R ", "C "):
            next(it, None)                  # rename/copy 的 old 占位跳过
    want = [p for p in paths if p.replace("\\", "/") in untracked]
    if want:
        _run(["git", "add", "--"] + want, wc, VCS_TIMEOUT_RW)


@vcs_bp.route("/api/vcs/add", methods=["POST"])
def vcs_add():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    paths = [str(p).replace("\\", "/") for p in (data.get("paths") or []) if p]
    if not paths or any(_bad_rel(p) for p in paths):
        return jsonify({"ok": False, "err": "未选择文件或路径非法"}), 400
    with _root_lock(wc):
        if vcs == "git":
            rc, out, e = _run(["git", "add", "--"] + paths, wc, VCS_TIMEOUT_RW)
        else:
            rc, out, e = _run(["svn", "add", "--"] + [
                os.path.join(wc, *p.split("/")) for p in paths], wc, VCS_TIMEOUT_RW)
        if rc != 0:
            return jsonify({"ok": False, "err": e or out or "add 失败"}), 500
    return jsonify({"ok": True, "out": (out or "").strip()})


@vcs_bp.route("/api/vcs/commit", methods=["POST"])
def vcs_commit():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    msg = str(data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "err": "提交说明必填"}), 400
    paths = [str(p).replace("\\", "/") for p in (data.get("paths") or []) if p]
    if not paths or any(_bad_rel(p) for p in paths):
        return jsonify({"ok": False, "err": "未选择文件或路径非法"}), 400
    with _root_lock(wc):
        if vcs == "git":
            _git_add_missing(wc, paths)
            rc, out, e = _run(["git", "commit", "-m", msg, "--"] + paths,
                              wc, VCS_TIMEOUT_RW)
            if rc != 0:
                return jsonify({"ok": False,
                                "err": (e or out or "commit 失败").strip()}), 500
            m = re.search(r"\[[\s\S]*? ([0-9a-f]{7,40})\]", out)
            return jsonify({"ok": True, "out": out.strip(),
                            **({"rev": m.group(1)} if m else {})})
        # svn：勾选中未跟踪（?）的先 svn add，再显式 target 提交
        rc, out, _e = _run(["svn", "status", "--xml"], wc, VCS_TIMEOUT_RO)
        if rc == 0:
            unv = []
            try:
                root = ET.fromstring(out.encode("utf-8"))
                for t in root.iter("target"):
                    for en in t.iter("entry"):
                        it = en.find("wc-status")
                        if it is not None and it.get("item") == "unversioned":
                            unv.append(en.get("path", "").replace("\\", "/"))
            except ET.ParseError:
                pass
            want = [os.path.join(wc, *p.split("/"))
                    for p in paths if p in unv]
            if want:
                _run(["svn", "add", "--"] + want, wc, VCS_TIMEOUT_RW)
        rc, out, e = _run(["svn", "commit", "-m", msg] + [
            os.path.join(wc, *p.split("/")) for p in paths], wc, VCS_TIMEOUT_NET)
        if rc != 0:
            return jsonify({"ok": False, "err": e or out or "commit 失败"}), 500
        return jsonify({"ok": True, "out": (out or "").strip()})


@vcs_bp.route("/api/vcs/update", methods=["POST"])
def vcs_update():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    with _root_lock(wc):
        if vcs == "git":
            rc, out, e = _run(["git", "pull", "--ff-only"], wc, VCS_TIMEOUT_NET)
        else:
            rc, out, e = _run(["svn", "update", "--accept", "postpone"],
                              wc, VCS_TIMEOUT_NET)
        text = (out or e or "").strip()
        if rc != 0:
            hint = ("本地与远端已分叉——本工具不含合并/冲突处理，"
                    "请在 git 命令行解决后刷新") if vcs == "git" else \
                   ("存在冲突（ postpone 保现场）——本工具不含冲突解决，"
                    "请用 svn 命令行/TortoiseSVN 处理后刷新")
            conflicts = sorted(set(re.findall(r"^\s*C\s+(.+)$", out or "",
                                              flags=re.M)))
            return jsonify({"ok": False, "err": hint, "out": text[:4000],
                            "conflicts": conflicts}), 500
        conflicts = sorted(set(re.findall(r"^\s*C\s+(.+)$", out or "",
                                          flags=re.M)))
        return jsonify({"ok": True, "out": text[:4000],
                        "conflicts": conflicts})
