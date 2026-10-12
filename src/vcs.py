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

from src.app_state import DATA_DIR
from src.file_tree import _under_roots

vcs_bp = Blueprint("vcs", __name__)

CREATE_NO_WINDOW = 0x08000000
VCS_TIMEOUT_RO = 20     # status/log/diff/show/cat
VCS_TIMEOUT_RW = 60     # add/commit
VCS_TIMEOUT_NET = 120   # pull/update
FILES_CAP = 500         # 改动列表上限（对齐 file_tree LIST_CAP 文化）
_LOG_CAP = 100
_TMP_KEEP_S = 24 * 3600
_TMP_MAX = 60

_ROOT_LOCKS = {}
_ROOT_LOCKS_GUARD = threading.Lock()


def _root_lock(wc_dir):
    """每个工作副本一把写锁——同仓 commit/update 串行，跨仓互不阻塞。"""
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(wc_dir, threading.Lock())


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
        p = subprocess.run([str(a) for a in argv], cwd=cwd,
                           capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
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


def _data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


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
        rel = tok[3:]
        if st == "R":                       # rename: new\0old
            old_rel = next(it, "")
            files.append({"rel": rel.replace("\\", "/"), "path": rel,
                          "st": "R", "old_rel": old_rel.replace("\\", "/")})
        else:
            files.append({"rel": rel.replace("\\", "/"), "path": rel, "st": st})
    rc, rev, _e = _run(["git", "rev-parse", "--short", "HEAD"], wc, 10)
    truncated = max(0, len(files) - FILES_CAP)
    return {"vcs": "git", "tool": True, "branch": branch, "rev": rev.strip(),
            "ahead": ahead, "behind": behind,
            "files": files[:FILES_CAP], "truncated": truncated}, None


def _svn_status(wc):
    rc, out, err = _run(["svn", "status", "--xml"], wc, VCS_TIMEOUT_RO)
    if rc != 0:
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
    truncated = max(0, len(files) - FILES_CAP)
    return {"vcs": "svn", "tool": True, "branch": branch, "rev": rev,
            "ahead": 0, "behind": 0,
            "files": files[:FILES_CAP], "truncated": truncated}, None


@vcs_bp.route("/api/vcs/status", methods=["POST"])
def vcs_status():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    res, e = (_git_status(wc) if vcs == "git" else _svn_status(wc))
    if e:
        return jsonify({"ok": False, "err": e}), 500
    return jsonify({"ok": True, **res})


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@vcs_bp.route("/api/vcs/log", methods=["POST"])
def vcs_log():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    try:
        limit = max(1, min(_LOG_CAP, int(data.get("limit") or 30)))
    except (TypeError, ValueError):
        limit = 30
    commits = []
    if vcs == "git":
        rc, out, e = _run(["git", "log", "-n", limit, "--date=iso-strict",
                           "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s"],
                          wc, VCS_TIMEOUT_RO)
        if rc != 0:
            if "does not have any commits yet" in (e or "") or rc == 128 and not out:
                return jsonify({"ok": True, "commits": []})
            return jsonify({"ok": False, "err": e or "git log 失败"}), 500
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 5:
                commits.append({"rev": parts[0], "short": parts[1],
                                "author": parts[2], "date": parts[3],
                                "msg": parts[4]})
    else:
        rc, out, e = _run(["svn", "log", "-l", limit, "--xml"], wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "svn log 失败"}), 500
        try:
            root = ET.fromstring(out.encode("utf-8"))
            for le in root.iter("logentry"):
                commits.append({"rev": le.get("revision", ""),
                                "short": "r%s" % le.get("revision", ""),
                                "author": le.findtext("author") or "",
                                "date": le.findtext("date") or "",
                                "msg": (le.findtext("msg") or "").strip()})
        except ET.ParseError as pe:
            return jsonify({"ok": False, "err": "svn log 解析失败：%s" % pe}), 500
    return jsonify({"ok": True, "commits": commits})


# ---------------------------------------------------------------------------
# diff（旧版本物化成临时文件，前端 buildDiffViewerTab 走真实路径）
# ---------------------------------------------------------------------------

def _git_old_bytes(wc, rel, st):
    if st == "A":                           # 新增文件：旧版为空
        return b""
    p = subprocess.run(["git", "show", "HEAD:%s" % rel], cwd=wc,
                       capture_output=True, timeout=VCS_TIMEOUT_RO,
                       creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        return b""
    return p.stdout


def _svn_old_bytes(wc, rel, st):
    if st == "A":
        return b""
    p = subprocess.run(["svn", "cat", "-r", "BASE", os.path.join(wc, rel)],
                       cwd=wc, capture_output=True, timeout=VCS_TIMEOUT_RO,
                       creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        return b""
    return p.stdout


@vcs_bp.route("/api/vcs/diff", methods=["POST"])
def vcs_diff():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    rel = str(data.get("path") or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
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

def _git_add_missing(wc, paths):
    """勾选中未跟踪的先 add（git 提交 pathspec 限定时未跟踪文件必须先入索引）。"""
    rc, out, _e = _run(["git", "-c", "core.quotepath=false",
                        "status", "--porcelain=v1", "-z"], wc, VCS_TIMEOUT_RO)
    if rc != 0:
        return
    untracked = set()
    toks = out.split("\0")
    it = iter(toks)
    for tok in it:
        if tok.startswith("? "):
            untracked.add(tok[2:].replace("\\", "/"))
        elif tok.startswith("R  "):
            next(it, None)                  # rename 的 old 占位跳过
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
    if not paths:
        return jsonify({"ok": False, "err": "未选择文件"}), 400
    if any(p.startswith("/") or ".." in p.split("/") for p in paths):
        return jsonify({"ok": False, "err": "非法文件路径"}), 400
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
    if not paths:
        return jsonify({"ok": False, "err": "未选择文件"}), 400
    if any(p.startswith("/") or ".." in p.split("/") for p in paths):
        return jsonify({"ok": False, "err": "非法文件路径"}), 400
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
